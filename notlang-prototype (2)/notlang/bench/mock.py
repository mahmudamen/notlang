"""An offline stand-in for a model: returns reference solutions, with scripted slips.

It exists to test the harness itself. Its numbers say nothing about real models.
"""
import copy
import json

from .reference import REFERENCE

SWAP = {"gt": "ge", "ge": "gt", "lt": "le", "le": "lt", "eq": "ne", "ne": "eq",
        "add": "sub", "sub": "add"}


def corrupt(graph, kind):
    g = copy.deepcopy(graph)
    if kind == "effects":            # forgets to declare effects -> caught by checker
        g["effects"] = []
    elif kind == "unknown_op":       # invents an op -> caught by checker
        g["nodes"]["zz"] = {"op": "avg", "in": [g["out"]]}
    elif kind == "semantic":         # valid but wrong -> only the cases can catch it
        for n in g["nodes"].values():
            if n["op"] in SWAP:
                n["op"] = SWAP[n["op"]]
                break
    return g


class MockModel:
    KINDS = ["none", "effects", "unknown_op", "semantic"]

    def __init__(self, slips=True):
        self.slips = slips

    def ask(self, task, system, messages):
        attempt = (len(messages) + 1) // 2
        graph = REFERENCE[task["id"]]
        if self.slips and attempt == 1:
            graph = corrupt(graph, self.KINDS[int(task["id"][1:]) % 4])
        return json.dumps(graph)
