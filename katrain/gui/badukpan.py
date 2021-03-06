import copy
import math
import time
from typing import List, Optional

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics.context_instructions import Color
from kivy.graphics.vertex_instructions import Ellipse, Line, Rectangle
from kivy.properties import ListProperty, ObjectProperty, BooleanProperty
from kivy.uix.dropdown import DropDown
from kivy.uix.widget import Widget
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.floatlayout import MDFloatLayout

from katrain.core.constants import MODE_PLAY, OUTPUT_DEBUG
from katrain.core.game import Move
from katrain.core.lang import i18n
from katrain.core.utils import evaluation_class, var_to_grid
from katrain.gui.kivyutils import draw_circle, draw_text, BackgroundMixin
from katrain.gui.style import *


class BadukPanWidget(Widget):
    def __init__(self, **kwargs):
        super(BadukPanWidget, self).__init__(**kwargs)
        self.trainer_config = {}
        self.ghost_stone = []
        self.gridpos_x = []
        self.gridpos_y = []
        self.grid_size = 0
        self.stone_size = 0
        self.active_pv_moves = []
        self.animating_pv = None
        self.last_mouse_pos = (0, 0)
        Window.bind(mouse_pos=self.on_mouse_pos)

        self.redraw_board_contents_trigger = Clock.create_trigger(self.draw_board_contents)
        self.redraw_trigger = Clock.create_trigger(self.redraw)
        self.bind(size=self.redraw_trigger)
        Clock.schedule_interval(self.animate_pv, 0.1)

    # stone placement functions
    def _find_closest(self, pos, gridpos):
        return sorted([(abs(p - pos), i) for i, p in enumerate(gridpos)])[0]

    def check_next_move_ghost(self, touch):
        if not self.gridpos_x:
            return
        xd, xp = self._find_closest(touch.x, self.gridpos_x)
        yd, yp = self._find_closest(touch.y, self.gridpos_y)
        prev_ghost = self.ghost_stone
        if max(yd, xd) < self.grid_size / 2 and (xp, yp) not in [m.coords for m in self.katrain.game.stones]:
            self.ghost_stone = (xp, yp)
        else:
            self.ghost_stone = None
        if prev_ghost != self.ghost_stone:
            self.draw_hover_contents()

    def on_touch_down(self, touch):
        self.animating_pv = None  # any click kills PV from label/move
        self.draw_hover_contents()
        if touch.button != "left":
            return
        self.check_next_move_ghost(touch)

    def on_touch_move(self, touch):
        return self.check_next_move_ghost(touch)

    def on_mouse_pos(self, *args):  # https://gist.github.com/opqopq/15c707dc4cffc2b6455f
        if self.get_root_window():  # don't proceed if I'm not displayed <=> If have no parent
            pos = args[1]
            rel_pos = self.to_widget(*pos)  # compensate for relative layout
            inside = self.collide_point(*rel_pos)
            if inside and self.active_pv_moves:
                near_move = [
                    (pv, node)
                    for move, pv, node in self.active_pv_moves
                    if abs(rel_pos[0] - self.gridpos_x[move[0]]) < self.grid_size / 2
                    and abs(rel_pos[1] - self.gridpos_y[move[1]]) < self.grid_size / 2
                ]
                if near_move:
                    self.set_animating_pv(near_move[0][0], near_move[0][1])
                else:
                    self.animating_pv = None
                    self.draw_hover_contents()
            if inside and self.animating_pv is not None:
                d_sq = (pos[0] - self.animating_pv[3][0]) ** 2 + (pos[1] - self.animating_pv[3][1])
                if d_sq > 2 * self.stone_size ** 2:  # move too far from where it was activated
                    self.animating_pv = None
                    self.draw_hover_contents()
            self.last_mouse_pos = pos

    def on_touch_up(self, touch):
        if touch.button != "left" or not self.gridpos_x:
            return
        katrain = self.katrain
        if self.ghost_stone and touch.button == "left":
            katrain("play", self.ghost_stone)
        elif not self.ghost_stone:
            xd, xp = self._find_closest(touch.x, self.gridpos_x)
            yd, yp = self._find_closest(touch.y, self.gridpos_y)

            nodes_here = [
                node for node in katrain.game.current_node.nodes_from_root if node.move and node.move.coords == (xp, yp)
            ]
            if nodes_here and max(yd, xd) < self.grid_size / 2:  # load old comment
                if touch.is_double_tap:  # navigate to move
                    katrain.game.set_current_node(nodes_here[-1])
                    katrain.update_state()
                else:  # load comments & pv
                    katrain.log(f"\nAnalysis:\n{nodes_here[-1].analysis}", OUTPUT_DEBUG)
                    katrain.log(f"\nParent Analysis:\n{nodes_here[-1].parent.analysis}", OUTPUT_DEBUG)
                    katrain.controls.info.text = nodes_here[-1].comment(sgf=True)
                    katrain.controls.active_comment_node = nodes_here[-1].parent
                    if nodes_here[-1].parent.analysis_ready:
                        self.set_animating_pv(nodes_here[-1].parent.candidate_moves[0]["pv"], nodes_here[-1].parent)

        self.ghost_stone = None
        self.draw_hover_contents()  # remove ghost

    # drawing functions
    def redraw(self, *_args):
        self.draw_board()
        self.draw_board_contents()

    def draw_stone(self, x, y, col, outline_col=None, innercol=None, evalcol=None, evalscale=1.0, scale=1.0):
        stone_size = self.stone_size * scale
        draw_circle((self.gridpos_x[x], self.gridpos_y[y]), stone_size, col)
        if outline_col:
            Color(*outline_col)
            Line(circle=(self.gridpos_x[x], self.gridpos_y[y], stone_size), width=min(2, 0.035 * stone_size))
        if evalcol:
            eval_radius = math.sqrt(evalscale)  # scale area by evalscale
            evalsize = self.stone_size * (EVAL_DOT_MIN_SIZE + eval_radius * (EVAL_DOT_MAX_SIZE - EVAL_DOT_MIN_SIZE))
            draw_circle((self.gridpos_x[x], self.gridpos_y[y]), evalsize, evalcol)

        if innercol:
            Color(*innercol)
            Line(circle=(self.gridpos_x[x], self.gridpos_y[y], stone_size * 0.475 / 0.85), width=0.1 * stone_size)

    def eval_color(self, points_lost, show_dots_for_class: List[bool] = None) -> Optional[List[float]]:
        i = evaluation_class(points_lost, self.trainer_config["eval_thresholds"])
        if show_dots_for_class is None or show_dots_for_class[i]:
            return EVAL_COLORS[i]

    def draw_board(self, *_args):
        if not (self.katrain and self.katrain.game):
            return
        katrain = self.katrain
        board_size_x, board_size_y = katrain.game.board_size

        with self.canvas.before:
            self.canvas.before.clear()
            # set up margins and grid lines
            grid_spaces_margin_x = [1.5, 0.75]  # left, right
            grid_spaces_margin_y = [1.5, 0.75]  # bottom, top
            x_grid_spaces = board_size_x - 1 + sum(grid_spaces_margin_x)
            y_grid_spaces = board_size_y - 1 + sum(grid_spaces_margin_y)
            self.grid_size = min(self.width / x_grid_spaces, self.height / y_grid_spaces)
            board_width_with_margins = x_grid_spaces * self.grid_size
            board_height_with_margins = y_grid_spaces * self.grid_size
            extra_px_margin_x = (self.width - board_width_with_margins) / 2
            extra_px_margin_y = (self.height - board_height_with_margins) / 2
            self.stone_size = self.grid_size * STONE_SIZE

            self.gridpos_x = [
                self.pos[0] + extra_px_margin_x + math.floor((grid_spaces_margin_x[0] + i) * self.grid_size + 0.5)
                for i in range(board_size_x)
            ]
            self.gridpos_y = [
                self.pos[1] + extra_px_margin_y + math.floor((grid_spaces_margin_y[0] + i) * self.grid_size + 0.5)
                for i in range(board_size_y)
            ]

            Color(*BOARD_COLOR)
            Rectangle(
                pos=(self.gridpos_x[0] - self.grid_size * 1.5, self.gridpos_y[0] - self.grid_size * 1.5),
                size=(self.grid_size * x_grid_spaces, self.grid_size * y_grid_spaces),
            )

            Color(*LINE_COLOR)
            for i in range(board_size_x):
                Line(points=[(self.gridpos_x[i], self.gridpos_y[0]), (self.gridpos_x[i], self.gridpos_y[-1])])
            for i in range(board_size_y):
                Line(points=[(self.gridpos_x[0], self.gridpos_y[i]), (self.gridpos_x[-1], self.gridpos_y[i])])

            # star points
            def star_point_coords(size):
                star_point_pos = 3 if size <= 11 else 4
                if size < 7:
                    return []
                return [star_point_pos - 1, size - star_point_pos] + (
                    [int(size / 2)] if size % 2 == 1 and size > 7 else []
                )

            starpt_size = self.grid_size * STARPOINT_SIZE
            for x in star_point_coords(board_size_x):
                for y in star_point_coords(board_size_y):
                    draw_circle((self.gridpos_x[x], self.gridpos_y[y]), starpt_size, LINE_COLOR)

            # coordinates
            Color(0.25, 0.25, 0.25)
            coord_offset = self.grid_size * 1.5 / 2
            for i in range(board_size_x):
                draw_text(
                    pos=(self.gridpos_x[i], self.gridpos_y[0] - coord_offset),
                    text=Move.GTP_COORD[i],
                    font_size=self.grid_size / 1.5,
                    font_name="Roboto",
                )
            for i in range(board_size_y):
                draw_text(
                    pos=(self.gridpos_x[0] - coord_offset, self.gridpos_y[i]),
                    text=str(i + 1),
                    font_size=self.grid_size / 1.5,
                    font_name="Roboto",
                )

    def draw_board_contents(self, *_args):
        if not (self.katrain and self.katrain.game):
            return
        katrain = self.katrain
        board_size_x, board_size_y = katrain.game.board_size
        show_n_eval = self.trainer_config["eval_off_show_last"]

        with self.canvas:
            self.canvas.clear()
            # stones
            current_node = katrain.game.current_node
            game_ended = katrain.game.ended
            full_eval_on = katrain.analysis_controls.eval.active
            has_stone = {}
            drawn_stone = {}
            for m in katrain.game.stones:
                has_stone[m.coords] = m.player

            show_dots_for = {
                p: self.trainer_config["eval_show_ai"] or katrain.players_info[p].human for p in Move.PLAYERS
            }
            show_dots_for_class = self.trainer_config["show_dots"]
            nodes = katrain.game.current_node.nodes_from_root
            realized_points_lost = None

            katrain.config("trainer/show_dots")
            for i, node in enumerate(nodes[::-1]):  # reverse order!
                points_lost = node.points_lost
                evalsize = 1
                if points_lost and realized_points_lost:
                    if points_lost <= 0.5 and realized_points_lost <= 1.5:
                        evalsize = 0
                    else:
                        evalsize = min(1, max(0, realized_points_lost / points_lost))
                for m in node.move_with_placements:
                    if has_stone.get(m.coords) and not drawn_stone.get(m.coords):  # skip captures, last only for
                        move_eval_on = show_dots_for.get(m.player) and (i < show_n_eval or full_eval_on)
                        if move_eval_on and points_lost is not None:
                            evalcol = self.eval_color(points_lost, show_dots_for_class)
                        else:
                            evalcol = None
                        inner = STONE_COLORS[m.opponent] if i == 0 else None
                        drawn_stone[m.coords] = m.player
                        self.draw_stone(
                            m.coords[0],
                            m.coords[1],
                            STONE_COLORS[m.player],
                            OUTLINE_COLORS[m.player],
                            inner,
                            evalcol,
                            evalsize,
                        )
                realized_points_lost = node.parent_realized_points_lost

            if katrain.game.current_node.is_root and katrain.debug_level >= 3:  # secret ;)
                for y in range(0, board_size_y):
                    evalcol = self.eval_color(16 * y / board_size_y)
                    self.draw_stone(0, y, STONE_COLORS["B"], OUTLINE_COLORS["B"], None, evalcol, y / (board_size_y - 1))
                    self.draw_stone(1, y, STONE_COLORS["B"], OUTLINE_COLORS["B"], STONE_COLORS["W"], evalcol, 1)
                    self.draw_stone(2, y, STONE_COLORS["W"], OUTLINE_COLORS["W"], None, evalcol, y / (board_size_y - 1))
                    self.draw_stone(3, y, STONE_COLORS["W"], OUTLINE_COLORS["W"], STONE_COLORS["B"], evalcol, 1)
                    self.draw_stone(4, y, [*evalcol[:3], 0.5], scale=0.8)

            # ownership - allow one move out of date for smooth animation
            ownership = current_node.ownership or (current_node.parent and current_node.parent.ownership)
            if katrain.analysis_controls.ownership.active and ownership:
                ownership_grid = var_to_grid(ownership, (board_size_x, board_size_y))
                rsz = self.grid_size * 0.2
                for y in range(board_size_y - 1, -1, -1):
                    for x in range(board_size_x):
                        ix_owner = "B" if ownership_grid[y][x] > 0 else "W"
                        if ix_owner != (has_stone.get((x, y), -1)):
                            Color(*STONE_COLORS[ix_owner][:3], abs(ownership_grid[y][x]))
                            Rectangle(pos=(self.gridpos_x[x] - rsz / 2, self.gridpos_y[y] - rsz / 2), size=(rsz, rsz))

            policy = current_node.policy
            if (
                not policy
                and current_node.parent
                and current_node.parent.policy
                and katrain.last_player_info.ai
                and katrain.next_player_info.ai
            ):
                policy = (
                    current_node.parent.policy
                )  # in the case of AI self-play we allow the policy to be one step out of date

            pass_btn = katrain.board_controls.pass_btn
            pass_btn.canvas.after.clear()
            if katrain.analysis_controls.policy.active and policy:
                policy_grid = var_to_grid(policy, (board_size_x, board_size_y))
                best_move_policy = max(*policy)
                for y in range(board_size_y - 1, -1, -1):
                    for x in range(board_size_x):
                        if policy_grid[y][x] > 0:
                            polsize = 1.1 * math.sqrt(policy_grid[y][x])
                            policy_circle_color = (
                                *POLICY_COLOR,
                                GHOST_ALPHA + TOP_MOVE_ALPHA * (policy_grid[y][x] == best_move_policy),
                            )
                            self.draw_stone(x, y, policy_circle_color, scale=polsize)
                polsize = math.sqrt(policy[-1])
                with pass_btn.canvas.after:
                    draw_circle(
                        (pass_btn.pos[0] + pass_btn.width / 2, pass_btn.pos[1] + pass_btn.height / 2),
                        polsize * pass_btn.height / 2,
                        POLICY_COLOR,
                    )

            # pass circle
            passed = len(nodes) > 1 and current_node.is_pass
            if passed:
                if game_ended:
                    text = katrain.game.manual_score or i18n._("board-game-end")
                else:
                    text = i18n._("board-pass")
                Color(0.45, 0.05, 0.45, 0.7)
                center = (self.gridpos_x[int(board_size_x / 2)], self.gridpos_y[int(board_size_y / 2)])
                size = min(self.width, self.height) * 0.22
                Ellipse(pos=(center[0] - size / 2, center[1] - size / 2), size=(size, size))
                Color(0.85, 0.85, 0.85)
                draw_text(
                    pos=center, text=text, font_size=size * 0.25, halign="center", outline_color=[0.95, 0.95, 0.95]
                )

        self.draw_hover_contents()

    def draw_hover_contents(self, *_args):
        ghost_alpha = GHOST_ALPHA
        katrain = self.katrain
        game_ended = katrain.game.ended
        current_node = katrain.game.current_node
        player, next_player = current_node.player, current_node.next_player
        stone_color = STONE_COLORS

        with self.canvas.after:
            self.canvas.after.clear()
            self.active_pv_moves = []

            # children of current moves in undo / review
            alpha = GHOST_ALPHA
            if katrain.analysis_controls.show_children.active:
                for child_node in current_node.children:
                    points_lost = child_node.points_lost
                    move = child_node.move
                    if move and move.coords is not None:
                        if points_lost is None:
                            evalcol = None
                        else:
                            evalcol = copy.copy(self.eval_color(points_lost))
                            evalcol[3] = alpha
                        if child_node.analysis_ready:
                            self.active_pv_moves.append(
                                (move.coords, [move.gtp()] + child_node.candidate_moves[0]["pv"], current_node)
                            )
                        scale = CHILD_SCALE
                        self.draw_stone(
                            move.coords[0],
                            move.coords[1],
                            (*stone_color[move.player][:3], alpha),
                            None,
                            None,
                            evalcol,
                            evalscale=scale,
                            scale=scale,
                        )

            # hints or PV
            if katrain.analysis_controls.hints.active and not game_ended:
                hint_moves = current_node.candidate_moves
                for i, move_dict in enumerate(hint_moves):
                    move = Move.from_gtp(move_dict["move"])
                    if move.coords is not None:
                        alpha, scale = GHOST_ALPHA, 1.0
                        if i == 0:
                            alpha += TOP_MOVE_ALPHA
                        elif move_dict["visits"] < VISITS_FRAC_SMALL * hint_moves[0]["visits"]:
                            scale = 0.8
                        if "pv" in move_dict:
                            self.active_pv_moves.append((move.coords, move_dict["pv"], current_node))
                        else:
                            katrain.log(f"PV missing for move_dict {move_dict}", OUTPUT_DEBUG)
                        self.draw_stone(
                            move.coords[0],
                            move.coords[1],
                            [*self.eval_color(move_dict["pointsLost"])[:3], alpha],
                            scale=scale,
                        )

            # hover next move ghost stone
            if self.ghost_stone:
                self.draw_stone(*self.ghost_stone, (*stone_color[next_player][:3], ghost_alpha))

            animating_pv = self.animating_pv
            if animating_pv:
                pv, node, start_time, _ = animating_pv
                delay = self.trainer_config.get("anim_pv_time", 0.5)
                up_to_move = (time.time() - start_time) / delay
                self.draw_pv(pv, node, up_to_move)

    def animate_pv(self, _dt):
        if self.animating_pv:
            self.draw_hover_contents()

    def draw_pv(self, pv, node, up_to_move):
        katrain = self.katrain
        next_last_player = [node.next_player, node.player]
        stone_color = STONE_COLORS
        cn = katrain.game.current_node
        if node != cn and node.parent != cn:
            hide_node = cn
            while hide_node and hide_node.move and hide_node != node:
                if not hide_node.move.is_pass:
                    self.draw_stone(*hide_node.move.coords, [0.85, 0.68, 0.40, 0.8])  # board coloured dot
                hide_node = hide_node.parent
        for i, gtpmove in enumerate(pv):
            if i > up_to_move:
                return
            move_player = next_last_player[i % 2]
            coords = Move.from_gtp(gtpmove).coords
            if coords is None:  # tee-hee
                sizefac = katrain.board_controls.pass_btn.size[1] / 2 / self.stone_size
                board_coords = [
                    katrain.board_controls.pass_btn.pos[0]
                    + katrain.board_controls.pass_btn.size[0]
                    + self.stone_size * sizefac,
                    katrain.board_controls.pass_btn.pos[1] + katrain.board_controls.pass_btn.size[1] / 2,
                ]
            else:
                board_coords = (self.gridpos_x[coords[0]], self.gridpos_y[coords[1]])
                sizefac = 1

            draw_circle(board_coords, self.stone_size * sizefac, stone_color[move_player])
            Color(*STONE_TEXT_COLORS[move_player])
            draw_text(pos=board_coords, text=str(i + 1), font_size=self.grid_size * sizefac / 1.45, font_name="Roboto")

    def set_animating_pv(self, pv, node):
        if node is not None and (
            not self.animating_pv or not (self.animating_pv[0] == pv and self.animating_pv[1] == node)
        ):
            self.animating_pv = (pv, node, time.time(), self.last_mouse_pos)

    def show_pv_from_comments(self, pv_str):
        self.set_animating_pv(pv_str[1:].split(" "), self.katrain.controls.active_comment_node.parent)


class AnalysisDropDown(DropDown):
    pass


class AnalysisControls(MDBoxLayout):
    dropdown = ObjectProperty(None)
    is_open = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.build_dropdown()

    def on_is_open(self, instance, value):
        if value:
            max_content_width = max(option.content_width for option in self.dropdown.container.children)
            self.dropdown.width = max_content_width
            self.dropdown.open(self.analysis_button)
        elif self.dropdown.attach_to:
            self.dropdown.dismiss()

    def close_dropdown(self, *largs):
        self.is_open = False

    def toggle_dropdown(self, *largs):
        self.is_open = not self.is_open

    def build_dropdown(self):
        self.dropdown = AnalysisDropDown(auto_width=False)
        self.dropdown.bind(on_dismiss=self.close_dropdown)


class BadukPanControls(MDFloatLayout):
    engine_status_col = ListProperty(ENGINE_DOWN_COL)
