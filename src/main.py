from typing import Dict, Tuple

from tabulate import tabulate

from data import Data
from distance import PDist
from models.explainers import DTreeExplainer
from models.explainers.base import BaseExplainer
from models.explainers.range import RangeExplainer
from models.hyperparameters import Hyperparameter
from models.optimizers import SwayOptimizer, SwayHyperparameterOptimizer, SwayWithPCAAlpha2Optimizer
from models.optimizers.base import BaseOptimizer
from options import options
from stats import cliffs_delta, bootstrap

help_ = """

project: multi-goal semi-supervised algorithms
(c) Group 9
  
USAGE: python3 main.py [OPTIONS] [-g ACTIONS]
  
OPTIONS:
  -b  --bins        initial number of bins           = 16
  -c  --cliff       cliff's delta threshold          = .147
  -d  --D           different is over sd*d           = .35
  -F  --Far         distance to distant              = .95
  -h  --help        show help                        = false
  -H  --Halves      search space for clustering      = 512
  -I  --IMin        size of smallest cluster         = .5
  -M  --Max         numbers                          = 512
  -p  --P           dist coefficient                 = 2
  -R  --Rest        how many of rest to sample       = 10
  -r  --reuse       child splits reuse a parent pole = true
  -x  --Bootstrap   number of samples to bootstrap   = 512    
  -o  --Conf        confidence interval              = 0.05
  -f  --file        file to generate table of        = ../data/auto2.csv
  -n  --Niter       number of iterations to run      = 20
  -w  --wColor      output with color                = true
  -T  --test        test particular algorithm        = false
  -a  --algo        name of the algorithm            = sway
"""


class ResultsGenerator:
    def __init__(self,
                 data_src: str,
                 base_optimizer: Tuple[str, BaseOptimizer] = None, optimizers: Dict[str, BaseOptimizer] = None,
                 base_explainer: Tuple[str, BaseExplainer] = None, explainers: [str, BaseExplainer] = None,
                 n_iters=20):
        self._data = None
        self._data_src = data_src
        self._n_iters = n_iters

        self._base_optimizer: Tuple[str, BaseOptimizer] = base_optimizer or \
                                                          ("sway", SwayOptimizer(**Hyperparameter.DEFAULT))
        self._optimizers = optimizers or {}

        self._base_explainer: Tuple[str, BaseExplainer] = base_explainer or ("xpln", RangeExplainer())
        self._explainers = explainers or {}

        self._results = self._get_results()
        self._n_evals = self._get_n_evals()
        self._ranks = self._get_ranks()
        self._time_taken = self._get_time_taken()

        self._comparisons = self._get_comparisons()

    def _get_comparisons(self):
        comparisons = [[["all", "all"], None], [["all", self._base_optimizer[0]], None], ]

        for optimizer in self._optimizers:
            comparisons.append([["all", optimizer], None])
            comparisons.append([[self._base_optimizer[0], optimizer], None])

        comparisons.append([[self._base_optimizer[0], self._base_explainer[0]], None])

        for explainer in self._explainers:
            comparisons.append([[self._base_optimizer[0], explainer], None])
            comparisons.append([[self._base_explainer[0], explainer], None])

        for optimizer in self._optimizers:
            comparisons.append([[optimizer, "top"], None])

        return comparisons

    def _get_results(self):
        optimizers = ["all", self._base_optimizer[0], ] + \
                     list(self._optimizers.keys()) + \
                     [self._base_explainer[0], ] + \
                     list(self._explainers.keys()) + \
                     ["top", ]

        return {optimizer: [] for optimizer in optimizers}

    def _get_n_evals(self):
        optimizers = ["all", self._base_optimizer[0], ] + \
                     list(self._optimizers.keys()) + \
                     [self._base_explainer[0], ] + \
                     list(self._explainers.keys()) + \
                     ["top", ]

        return {optimizer: 0 for optimizer in optimizers}

    def _get_ranks(self):
        optimizers = ["all", self._base_optimizer[0], ] + \
                     list(self._optimizers.keys()) + \
                     [self._base_explainer[0], ] + \
                     list(self._explainers.keys()) + \
                     ["top", ]

        return {optimizer: 0 for optimizer in optimizers}

    def _get_time_taken(self):
        optimizers = ["all", self._base_optimizer[0], ] + \
                     list(self._optimizers.keys()) + \
                     [self._base_explainer[0], ] + \
                     list(self._explainers.keys()) + \
                     ["top", ]

        return {optimizer: 0 for optimizer in optimizers}

    def _mean(self, l):
        return sum(l) / len(l)

    def run(self):
        i = 0

        self._data = Data(self._data_src)
        # get the "top" results by running the betters algorithm
        all_ranked = self._data.betters()
        # for each row, rank it normalized from 1-100
        for idx, row in enumerate(all_ranked):
            row.rank = 1 + (idx / len(self._data.rows)) * 99

        while i < self._n_iters:

            self._results["all"].append(self._data)
            self._n_evals["all"] += 0
            self._ranks["all"] += self._mean([r.rank for r in self._data.rows])

            # Base Optimizer
            rules_satisfied = False

            while not rules_satisfied:
                rules_result_dict = {}
                rules_satisfied = True

                (best, rest, evals), time = self._base_optimizer[1].run(data=self._data)

                rule_0, xpln_0_time = self._base_explainer[1].xpln(self._data, best, rest)

                if rule_0 == -1:
                    rules_satisfied = False
                    continue

                rules_result_dict[self._base_explainer[0]] = \
                    (Data.clone(self._data, RangeExplainer.selects(rule_0, self._data)), xpln_0_time)

                for e_name, explainer in self._explainers.items():
                    rule_i, xpln_i_time = explainer.xpln(self._data, best, rest)

                    if rule_i == -1:
                        rules_satisfied = False
                        break

                    rules_result_dict[e_name] = \
                        (Data.clone(self._data, explainer.selects(rule_i, self._data)), xpln_i_time)

                self._results[self._base_optimizer[0]].append(best)
                self._n_evals[self._base_optimizer[0]] += evals
                self._ranks[self._base_optimizer[0]] += self._mean([r.rank for r in best.rows])
                self._time_taken[self._base_optimizer[0]] += time

                for rule in rules_result_dict:
                    self._results[rule].append(rules_result_dict[rule][0])
                    self._n_evals[rule] += evals
                    self._ranks[rule] += self._mean([r.rank for r in rules_result_dict[rule][0].rows])
                    self._time_taken[rule] += rules_result_dict[rule][1]

                top2, _ = self._data.betters(len(best.rows))
                top = Data.clone(self._data, top2)

                self._results['top'].append(top)
                self._n_evals["top"] += len(self._data.rows)
                self._ranks["top"] += self._mean([r.rank for r in top.rows])

            for o_name, optimizer in self._optimizers.items():
                (best, rest, evals), time = optimizer.run(data=self._data)

                self._results[o_name].append(best)
                self._n_evals[o_name] += evals
                self._ranks[o_name] += self._mean([r.rank for r in best.rows])
                self._time_taken[o_name] += time

            self._update_comparisons(i)

            i += 1

    def _update_comparisons(self, iter_: int):
        for i in range(len(self._comparisons)):
            [base, diff], result = self._comparisons[i]

            if result is None:
                self._comparisons[i][1] = ["=" for _ in range(len(self._data.cols.y))]

            for k in range(len(self._data.cols.y)):
                if self._comparisons[i][1][k] == "=":
                    base_y, diff_y = self._results[base][iter_].cols.y[k], self._results[diff][iter_].cols.y[k]
                    equals = bootstrap(base_y.has(), diff_y.has()) and cliffs_delta(base_y.has(), diff_y.has())

                    if not equals:
                        if i == 0:
                            print("WARNING: all to all {} {} {}".format(i, k, "false"))
                            print(f"all to all comparison failed for {self._results[base][iter_].cols.y[k].txt}")

                        self._comparisons[i][1][k] = "≠"

    def print_table(self, color: bool):
        headers = [y.txt for y in self._data.cols.y]
        table = []

        for k, v in self._results.items():
            # set the row equal to the average stats
            stats = get_stats(v)
            stats_list = [stats[y] for y in headers]

            # adds on the average number of evals
            stats_list += [self._n_evals[k] / self._n_iters]
            # adds on average rank of rows
            stats_list += [self._ranks[k] / self._n_iters]
            stats_list += [self._time_taken[k] / self._n_iters]

            stats_list = [round(r, 1) for r in stats_list]

            table.append([k] + stats_list)

        maxes = []

        for i in range(len(headers)):
            optimizer_vals = []
            explainer_vals = []

            for v in table:
                if v[0] in self._optimizers or v[0] == self._base_optimizer[0]:
                    optimizer_vals.append({"algo": v[0], "value": v[i + 1]})
                elif v[0] in self._explainers or v[0] == self._base_explainer[0]:
                    explainer_vals.append({"algo": v[0], "value": v[i + 1]})

            optimizer_vals = sorted(optimizer_vals, key=lambda x: x["value"], reverse=(headers[i][-1] == "+"))
            explainer_vals = sorted(explainer_vals, key=lambda x: x["value"], reverse=(headers[i][-1] == "+"))

            optimizer_vals_dict = {d["algo"]: rank for rank, d in enumerate(optimizer_vals)}
            explainer_vals_dict = {d["algo"]: rank for rank, d in enumerate(explainer_vals)}

            max_ = [
                headers[i],
                optimizer_vals[0]["algo"],
            ]

            for optimizer in self._optimizers:
                max_.append(optimizer_vals_dict[optimizer] < optimizer_vals_dict[self._base_optimizer[0]])

            for explainer in self._explainers:
                max_.append(explainer_vals_dict[explainer] < explainer_vals_dict[self._base_explainer[0]])

            maxes.append(max_)

        if color:
            for i in range(len(headers)):
                # get the value of the 'y[i]' column for each algorithm
                header_vals = [v[i + 1] for v in table]

                # if the 'y' value is minimizing, use min else use max
                fun = max if headers[i][-1] == "+" else min

                # change the table to have green text if it is the "best" for that column
                table[header_vals.index(fun(header_vals))][i + 1] = '\033[92m' + str(
                    table[header_vals.index(fun(header_vals))][i + 1]) + '\033[0m'

        print(tabulate(table, headers=headers + ["Avg evals", "Avg rank", "Avg Time Taken"], numalign="right",
                       tablefmt="latex"))
        print()

        m_headers = ["Best", ]

        for optimizer in self._optimizers:
            m_headers.append(f"{optimizer} beat {self._base_optimizer[0]}?")

        for explainer in self._explainers:
            m_headers.append(f"{explainer} beat {self._base_explainer[0]}?")

        print(tabulate(maxes, headers=m_headers, numalign="right"))
        print()

        # generates the =/!= table
        table = []

        # for each comparison of the algorithms
        #    append the = / !=
        for [base, diff], result in self._comparisons:
            table.append([f"{base} to {diff}"] + result)

        print(tabulate(table, headers=headers, numalign="right", tablefmt="latex"))


def get_stats(data_array):
    # gets the average stats, given the data array objects
    res = {}

    # accumulate the stats
    for item in data_array:
        stats = item.stats()

        # update the stats
        for k, v in stats.items():
            res[k] = res.get(k, 0) + v

    # right now, the stats are summed. change it to average
    for k, v in res.items():
        res[k] /= options["Niter"]

    return res


def main():
    """
    `main` runs each algorithm for 20 iterations, on the given file dataset.

    It accumulates the results per each iteration, and compares the algorithms
    using cliffsDelta and bootstrap

    It then produces summatory stats, including a mean table (for each algorithm,
    summarize each y column and number of iterations)
    And a table comparing each algorithm to each other using cliffsDelta and bootstrap
    """

    options.parse_cli_settings(help_)

    if options["help"]:
        print(help_)
    elif options["test"]:
        algorithm = options["algo"]

        optimizers = {
            "sway": SwayOptimizer(
                reuse=options["reuse"],
                far=options["Far"],
                halves=options["Halves"],
                rest=options["Rest"],
                i_min=options["IMin"],
                distance_class=PDist(options["P"])
            ),
            "sway_optimized_hp": SwayOptimizer(**Hyperparameter.OPTIMIZED),
            "sway_pca_as": SwayWithPCAAlpha2Optimizer(
                reuse=options["reuse"],
                far=options["Far"],
                halves=options["Halves"],
                rest=options["Rest"],
                i_min=options["IMin"],
                distance_class=PDist(options["P"])
            ),
            "sway_hp_search": SwayHyperparameterOptimizer(
                reuse=options["reuse"],
                far=options["Far"],
                halves=options["Halves"],
                rest=options["Rest"],
                i_min=options["IMin"],
                distance_class=PDist(options["P"])
            ),
        }

        explainers = {
            "xpln": RangeExplainer(),
            "xpln_dtree": DTreeExplainer(),
        }

        if algorithm in optimizers.keys():
            rg = ResultsGenerator(
                base_optimizer=("base_sway", SwayOptimizer(**Hyperparameter.DEFAULT)),
                base_explainer=("base_xpln", RangeExplainer()),
                data_src=options["file"],
                optimizers={algorithm: optimizers[algorithm]},
            )
        elif algorithm in explainers.keys():
            rg = ResultsGenerator(
                base_optimizer=("base_sway", SwayOptimizer(**Hyperparameter.DEFAULT)),
                base_explainer=("base_xpln", RangeExplainer()),
                data_src=options["file"],
                explainers={algorithm: explainers[algorithm]},
            )
            rg.run()

            rg.print_table(color=options["wColor"])
        else:
            print(
                f"algo can only accept these Values:\n"
                f"Optimizers: {list(optimizers.keys())}\n"
                f"Explainers:{list(explainers.keys())}"
            )
    else:
        optimizers = {
            "sway2": SwayOptimizer(**Hyperparameter.OPTIMIZED),
            "sway3": SwayWithPCAAlpha2Optimizer(**Hyperparameter.DEFAULT),
        }

        rg = ResultsGenerator(data_src=options["file"], optimizers=optimizers, explainers={"xpln2": DTreeExplainer()})
        rg.run()

        rg.print_table(color=options["wColor"])


main()
