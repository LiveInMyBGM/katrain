import copy
import random
from typing import Dict, List, Optional, Tuple

from common import var_to_grid
from sgf_parser import Move, SGFNode


class GameNode(SGFNode):
    """Represents a single game node, with one or more moves and placements."""

    def __init__(self, parent=None, properties=None, move=None):
        super().__init__(parent=parent, properties=properties, move=move)
        self.analysis = {"moves": {}, "root": None}
        self.ownership = None
        self.policy = None
        self.auto_undo = None  # None = not analyzed. False: not undone (good move). True: undone (bad move)
        self.ai_thoughts = ""
        self.move_number = 0
        self.undo_threshold = random.random()  # for fractional undos, store the random threshold in the move itself for consistency

    @property
    def sgf_properties(self):
        best_sq = []
        properties = copy.copy(super().sgf_properties)
        if best_sq and "SQ" not in properties:
            properties["SQ"] = best_sq
        comment = self.comment(sgf=True)
        if comment:
            properties["C"] = [properties.get("C", "") + comment]
        return properties

    # various analysis functions
    def analyze(self, engine, priority=0, visits=None, time_limit=True, refine_move=None):
        engine.request_analysis(self, lambda result: self.set_analysis(result, refine_move), priority=priority, visits=visits, time_limit=time_limit, next_move=refine_move)

    def update_move_analysis(self, move_analysis, move_gtp):
        cur = self.analysis["moves"].get(move_gtp)
        if cur is None:
            self.analysis["moves"][move_gtp] = {"move": move_gtp, "order": 999, **move_analysis}  # some default values for keys missing in rootInfo
        elif cur["visits"] < move_analysis["visits"]:
            cur.update(move_analysis)

    def set_analysis(self, analysis_json, refine_move):
        if refine_move:
            pvtail = analysis_json["moveInfos"][0]["pv"] if analysis_json["moveInfos"] else []
            self.update_move_analysis({"pv": [refine_move.gtp()] + pvtail, **analysis_json["rootInfo"]}, refine_move.gtp())
        else:
            for move_analysis in analysis_json["moveInfos"]:
                self.update_move_analysis(move_analysis, move_analysis["move"])
            self.ownership = analysis_json.get("ownership")
            self.policy = analysis_json.get("policy")
            self.analysis["root"] = analysis_json["rootInfo"]

    @property
    def analysis_ready(self):
        return self.analysis["root"] is not None

    def format_score(self, score=None):
        score = score or self.score
        if score:
            return f"{'B' if score >= 0 else 'W'}+{abs(score):.1f}"

    def format_win_rate(self, win_rate=None):
        win_rate = win_rate or self.analysis["root"].get("winrate")
        if win_rate:
            return f"{'B' if win_rate > 0.5 else 'W'} {max(win_rate,1-win_rate):.1%}"

    def comment(self, sgf=False, teach=False, hints=False):
        single_move = self.single_move
        if not self.parent or not single_move:  # root
            return ""

        text = f"Move {self.depth}: {single_move.player} {single_move.gtp()}\n"
        if self.analysis_ready:
            score = self.score
            if sgf:
                text += f"Score: {self.format_score(score)}\n"
                text += f"Win Rate: {self.format_win_rate()}\n"
            if self.parent and self.parent.analysis_ready:
                previous_top_move = self.parent.candidate_moves[0]
                if sgf or hints:
                    if previous_top_move["move"] != single_move.gtp():
                        text += f"Predicted top move was {previous_top_move['move']} ({self.format_score(previous_top_move['scoreLead'])}).\n"
                        points_lost = self.points_lost
                        if sgf and points_lost > 0.5:
                            text += f"Estimated point loss: {points_lost:.1f}\n"
                    else:
                        text += f"Move was predicted best move.\n"
                if sgf or hints or teach:
                    policy_ranking = self.parent.policy_ranking
                    policy_ix = [ix + 1 for (p, m), ix in zip(policy_ranking, range(len(policy_ranking))) if m == single_move]
                    if policy_ix:
                        text += f"Move was #{policy_ix[0]} according to policy.\n"
                    if not policy_ix or policy_ix[0] != 1 and (sgf or hints):
                        text += f"Top policy move was {policy_ranking[0][1].gtp()} ({policy_ranking[0][0]:.1%}).\n"
            if self.auto_undo and sgf:
                text += "Move was automatically undone in teaching mode."
            if self.ai_thoughts:
                text += f"\nAI thought process: {self.ai_thoughts}"
        else:
            text = "No analysis available" if sgf else "Analyzing move..."
        return text

    @property
    def points_lost(self) -> Optional[float]:
        single_move = self.single_move
        if single_move and self.parent and self.analysis_ready and self.parent.analysis_ready:
            parent_score = self.parent.score
            score = self.score
            return self.player_sign(single_move.player) * (parent_score - score)

    @property
    def score(self) -> Optional[float]:
        if self.analysis_ready:
            return self.analysis["root"]["scoreLead"]

    @staticmethod
    def player_sign(player):
        return {"B": 1, "W": -1, None: 0}[player]

    @property
    def candidate_moves(self) -> List[Dict]:
        if not self.analysis_ready:
            return []
        if not self.analysis["moves"]:
            polmoves = self.policy_ranking
            top_polmove = polmoves[0][1] if polmoves else Move(None)  # if no info at all, pass
            return [{**self.analysis["root"], "pointsLost": 0, "order": 0, "move": top_polmove.gtp()}]  # single visit -> go by policy/root

        return sorted(
            [{"pointsLost": self.player_sign(self.next_player) * (self.analysis["root"]["scoreLead"] - d["scoreLead"]), **d} for d in self.analysis["moves"].values()],
            key=lambda d: (d["order"], d["pointsLost"]),
        )

    @property
    def policy_ranking(self) -> Optional[List[Tuple[float, Move]]]:  # return moves from highest policy value to lowest
        if self.policy:
            szx, szy = self.board_size
            policy_grid = var_to_grid(self.policy, size=(szx, szy))
            moves = [(policy_grid[y][x], Move((x, y), player=self.next_player)) for x in range(szx) for y in range(szy)]
            moves.append((self.policy[-1], Move(None, player=self.next_player)))
            return sorted(moves, key=lambda mp: -mp[0])
