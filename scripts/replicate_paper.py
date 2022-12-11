"""\
Run the benchmark multiple times with a range of settings,
and produce tables / graphs with these results
"""

import argparse
import sys
import logging
import subprocess
import datetime
import os
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import numpy as np
import math
import time
import pandas as pd

# Home dir should be continuum/
os.chdir("../")


def enable_logging(verbose):
    """Enable logging"""
    # Set parameters
    level = logging.INFO
    if verbose:
        level = logging.DEBUG

    format = "[%(asctime)s %(filename)20s:%(lineno)4s - %(funcName)25s() ] %(message)s"
    logging.basicConfig(format=format, level=level, datefmt="%Y-%m-%d %H:%M:%S")

    logging.info("Logging has been enabled")


class Experiment:
    """Experiment template / super class"""

    def __init__(self, resume):
        self.resume = resume
        self.runs = []

    def check_resume(self):
        """If the resume argument is given, get the first x log files >= the resume date,
        and use their output instead of re-running the experiment.
        """
        if self.resume == None:
            return

        log_location = "./logs"
        logs = [f for f in os.listdir(log_location) if f.endswith(".log")]
        logs.sort()
        exp_i = 0

        for log in logs:
            splits = log.split("_")
            dt = splits[0] + "_" + splits[1]
            dt = datetime.datetime.strptime(dt, "%Y-%m-%d_%H:%M:%S")

            if dt >= self.resume:
                path = os.path.join(log_location, log)
                logging.info("File %s for experiment run %i" % (path, exp_i))

                f = open(path, "r")
                output = [line for line in f.readlines()]
                f.close()

                self.runs[exp_i]["output"] = output
                exp_i += 1

                # We have all logs needed
                if exp_i == len(self.runs):
                    break

    def run_commands(self):
        """Execute all generated commands"""
        for run in self.runs:
            if run["command"] == []:
                continue

            # Skip runs where we got output with --resume
            if run["output"] != None:
                logging.info("Skip command: %s" % (" ".join(run["command"])))
                continue

            output, error = self.execute(run["command"])

            logging.debug("------------------------------------")
            logging.debug("OUTPUT")
            logging.debug("------------------------------------")
            logging.debug("\n" + "".join(output))

            if error != []:
                logging.debug("------------------------------------")
                logging.debug("ERROR")
                logging.debug("------------------------------------")
                logging.debug("\n" + "".join(error))
                sys.exit()

            logging.debug("------------------------------------")

            # Get output from log file
            logpath = output[0].rstrip().split("and file at ")[-1]
            f = open(logpath, "r")
            output = [line for line in f.readlines()]
            run["output"] = output
            f.close()

    def execute(self, command):
        """Execute a process using the subprocess library, and return the output/error or the process

        Args:
            command (list(str)): Command to be executed.

        Returns:
            (list(str), list(str)): Return the output and error generated by this process.
        """
        logging.info(" ".join(command))
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output = [line.decode("utf-8") for line in process.stdout.readlines()]
        error = [line.decode("utf-8") for line in process.stderr.readlines()]
        return output, error


class EndpointScaling(Experiment):
    """Experiment:
    System load with an increasing number of endpoints connected to a singleworker

    So:
    - Run with all 3 deployment modes
    - Vary number of endpoints connected to a single worker
    """

    def __init__(self, resume):
        Experiment.__init__(self, resume)

        self.modes = ["cloud", "edge", "endpoint"]
        self.cores = [4, 2, 1]
        self.endpoints = [1, 2, 4, 8]

        self.y = None

    def __repr__(self):
        """Returns this string when called as print(object)"""
        return """
APP                     image-classification
MODES                   %s
WORKERS                 1
CLOUD_CORES             %i
EDGE_CORES              %i
ENDPOINT_CORES          %i
ENDPOINTS/WORKER        %s""" % (
            ",".join(self.modes),
            self.cores[0],
            self.cores[1],
            self.cores[2],
            ",".join([str(endpoint) for endpoint in self.endpoints]),
        )

    def generate(self):
        """Generate commands to run the benchmark based on the current settings"""
        # Differ in deployment modes
        for mode in self.modes:
            if mode == "cloud":
                config = "cloud_endpoint"
                cores = self.cores[0]
            elif mode == "edge":
                config = "edge_endpoint"
                cores = self.cores[1]
            else:
                config = "endpoint"
                cores = self.cores[2]

            # Differ in #endpoints per worker
            for endpoint in self.endpoints:
                # No sense to use more than 1 endpoint in endpoint-only deployment mode
                if mode == "endpoint" and endpoint > 1:
                    continue

                command = [
                    "python3",
                    "main.py",
                    "-v",
                    "configuration/experiment_endpoint_scaling/" + config + str(endpoint) + ".cfg",
                ]
                command = [str(c) for c in command]

                run = {
                    "mode": mode,
                    "cores": cores,
                    "endpoints": endpoint,
                    "command": command,
                    "output": None,
                    "worker_time": None,
                }
                self.runs.append(run)

    def parse_output(self):
        """For all runs, get the worker runtime"""
        for run in self.runs:
            # Get the line containing the metrics
            for i, line in enumerate(run["output"]):
                if "Output in csv format" in line:
                    break

            # Get output based on type of run
            if run["mode"] != "endpoint":
                worker = run["output"][i + 1][1:-4]
                endpoint = run["output"][i + 2][1:-4]
            else:
                worker = run["output"][i + 1][1:-4]
                endpoint = run["output"][i + 1][1:-4]

            # Get worker output, parse into dataframe
            w1 = [x.split(",") for x in worker.split("\\n")]
            w2 = [sub[1:] for sub in w1]
            wdf = pd.DataFrame(w2[1:], columns=w2[0])
            wdf["proc_time/data (ms)"] = pd.to_numeric(wdf["proc_time/data (ms)"], downcast="float")

            # Get endpoint output, parse into dataframe
            e1 = [x.split(",") for x in endpoint.split("\\n")]
            e2 = [sub[1:] for sub in e1]
            edf = pd.DataFrame(e2[1:], columns=e2[0])
            edf["latency_avg (ms)"] = pd.to_numeric(edf["latency_avg (ms)"], downcast="float")

            # For worker, get the number of images processed per second across all cores
            processed_rate = wdf["proc_time/data (ms)"].mean()
            processed_rate = 1000.0 / processed_rate
            processed_rate *= run["cores"]

            # Calculate the generated number of images per second by endpoints
            frequency = 5
            requested_rate = float(frequency * run["endpoints"])

            # Calculate the utilization by comparing the generated workload to
            # the time it took to process the workload
            run["usage"] = int((requested_rate / processed_rate) * 100)

            # For endpoint, report the average end-to-end latency
            run["latency"] = int(edf["latency_avg (ms)"].mean())

    def plot(self):
        # set width of bar
        plt.rcParams.update({"font.size": 22})
        fig, ax1 = plt.subplots(figsize=(12, 6))
        ax2 = ax1.twinx()

        barWidth = 0.2
        bars = np.arange(len(self.modes))

        colors = ["dimgray", "gray", "darkgray", "lightgray"]

        y_total_load = []
        y_total_latency = []
        xs = []
        for endpoint, color in zip(self.endpoints, colors):
            # Get the x and y data
            y = [run["usage"] for run in self.runs if run["endpoints"] == endpoint]
            x = [x + math.log2(endpoint) * barWidth for x in bars]

            # mode=endpoint only uses 1 endpoint
            if endpoint > 1:
                x = x[:-1]

            # Plot the bar
            if xs == []:
                # Only label for the first bar
                ax1.bar(
                    x,
                    y,
                    color=color,
                    width=barWidth * 0.9,
                    label="System Load",
                )
            else:
                ax1.bar(
                    x,
                    y,
                    color=color,
                    width=barWidth * 0.9,
                )

            y_total_load += y

            # For the latency line plot
            y = [run["latency"] for run in self.runs if run["endpoints"] == endpoint]
            y_total_latency += y
            xs += x

        # Plot latency line
        ys = y_total_latency
        xs, ys = zip(*sorted(zip(xs, ys)))
        ax2.plot(
            xs[:4],
            ys[:4],
            color="midnightblue",
            linewidth=3.0,
            marker="o",
            markersize=12,
        )
        ax2.plot(
            xs[4:8],
            ys[4:8],
            color="midnightblue",
            linewidth=3.0,
            marker="o",
            markersize=12,
        )
        ax2.plot(
            xs[8],
            ys[8],
            color="midnightblue",
            linewidth=3.0,
            marker="o",
            markersize=12,
        )

        # Add horizontal lines every 100 percent
        ax1.axhline(y=100, color="k", linestyle="-", linewidth=3)
        ax1.axhline(y=200, color="k", linestyle="-", linewidth=1, alpha=0.5)
        ax1.axhline(y=300, color="k", linestyle="-", linewidth=1, alpha=0.5)
        ax1.axhline(y=400, color="k", linestyle="-", linewidth=1, alpha=0.5)

        label_ticks = [
            i + j * barWidth
            for i, j in [
                (0, 0),
                (0, 1),
                (0, 2),
                (0, 3),
                (1, 0),
                (1, 1),
                (1, 2),
                (1, 3),
                (2, 0),
            ]
        ]
        ax1.set_xticks(label_ticks, ["1", "2", "4", "8", "1", "2", "4", "8", "1"])

        # Set y axis 1: load
        ax1.set_ylabel("System Load")
        ax1.legend(loc="upper left", framealpha=1.0)
        ax1.yaxis.set_major_formatter(mtick.PercentFormatter())
        ax1.set_ylim(0, 500)
        ax1.set_yticks(np.arange(0, 600, 100))

        # Set y axis 2: latency
        ax2.set_ylabel("End-to-end latency (ms)")
        ax2.set_yscale("log")
        ax2.set_ylim(100, 10000000)
        ax2.legend(["End-to-end latency"], loc="upper right", framealpha=1.0)

        # Save
        t = time.strftime("%Y-%m-%d_%H:%M:%S", time.gmtime())
        plt.savefig("./logs/EndpointScaling_load_%s.pdf" % (t), bbox_inches="tight")

        self.y_load = y_total_load
        self.y_latency = y_total_latency

    def print_result(self):
        i = 0
        for endpoint in self.endpoints:
            for mode in self.modes:
                if mode == "endpoint" and endpoint > 1:
                    break

                logging.info(
                    "Mode: %10s | Endpoints: %3s | System Load: %4i%% | Latency: %10i ms"
                    % (mode, endpoint, self.y_load[i], self.y_latency[i])
                )
                i += 1


class Deployments(Experiment):
    """Experiment:
    Run large scale cloud, edge, and endpoint deployments
    """

    def __init__(self, resume):
        Experiment.__init__(self, resume)

        self.config_path = "configuration/experiment_large_deployments/"
        self.configs = [
            "cloud.cfg",
            "edge_large.cfg",
            "edge_small.cfg",
            "mist.cfg",
        ]
        self.modes = ["cloud", "edge", "edge", "edge"]
        self.cores = [4, 4, 2, 2]
        self.endpoints = [4, 4, 2, 1]

        self.y = None

    def __repr__(self):
        """Returns this string when called as print(object)"""
        return """
APP                     image-classification
CONFIGS                 %s""" % (
            ",".join([str(config) for config in self.configs]),
        )

    def generate(self):
        """Generate commands to run the benchmark based on the current settings"""
        for config, mode, core, endpoint in zip(
            self.configs, self.modes, self.cores, self.endpoints
        ):
            command = ["python3", "main.py", "-v", self.config_path + config]
            command = [str(c) for c in command]

            run = {
                "mode": mode,
                "cores": core,
                "endpoints": endpoint,
                "config": config.split(".")[0],
                "command": command,
                "output": None,
                "worker_time": None,
            }
            self.runs.append(run)

    def parse_output(self):
        """For all runs, get the worker runtime"""
        for run in self.runs:
            # Get the line containing the metrics
            for i, line in enumerate(run["output"]):
                if "Output in csv format" in line:
                    break

            # Get output based on type of run
            if run["mode"] != "endpoint":
                worker = run["output"][i + 1][1:-4]
                endpoint = run["output"][i + 2][1:-4]
            else:
                worker = run["output"][i + 1][1:-4]
                endpoint = run["output"][i + 1][1:-4]

            # Get worker output, parse into dataframe
            w1 = [x.split(",") for x in worker.split("\\n")]
            w2 = [sub[1:] for sub in w1]
            wdf = pd.DataFrame(w2[1:], columns=w2[0])
            wdf["proc_time/data (ms)"] = pd.to_numeric(wdf["proc_time/data (ms)"], downcast="float")
            wdf["delay_avg (ms)"] = pd.to_numeric(wdf["delay_avg (ms)"], downcast="float")

            # Get endpoint output, parse into dataframe
            e1 = [x.split(",") for x in endpoint.split("\\n")]
            e2 = [sub[1:] for sub in e1]
            edf = pd.DataFrame(e2[1:], columns=e2[0])
            edf["latency_avg (ms)"] = pd.to_numeric(edf["latency_avg (ms)"], downcast="float")
            edf["preproc_time/data (ms)"] = pd.to_numeric(
                edf["preproc_time/data (ms)"], downcast="float"
            )

            # For worker, get the number of images processed per second across all cores
            processed_rate = wdf["proc_time/data (ms)"].min()
            processed_rate = 1000.0 / processed_rate
            processed_rate *= run["cores"]

            # Calculate the generated number of images per second by endpoints
            frequency = 5
            requested_rate = float(frequency * run["endpoints"])

            # Calculate the utilization by comparing the generated workload to
            # the time it took to process the workload
            run["usage"] = int((requested_rate / processed_rate) * 100)

            # For endpoint, report the average end-to-end latency
            run["latency"] = int(edf["latency_avg (ms)"].min())

            # Save breakdown of latency
            run["latency_breakdown"] = [
                int(wdf["proc_time/data (ms)"].min()),
                int(
                    edf["latency_avg (ms)"].min()
                    - edf["preproc_time/data (ms)"].min()
                    - wdf["proc_time/data (ms)"].min()
                ),
            ]

    def plot(self):
        # set width of bar
        plt.rcParams.update({"font.size": 22})
        fig, ax1 = plt.subplots(figsize=(12, 6))

        barWidth = 0.2

        y_total_load = []
        y_total_latency = []
        xs = []

        y = [run["usage"] for run in self.runs]
        x = [x * barWidth for x in range(len(self.configs))]

        ax1.bar(
            x,
            y,
            color="dimgray",
            width=barWidth * 0.9,
            label="System Load",
        )

        y_total_load += y

        # For the latency line plot
        y = [run["latency"] for run in self.runs]
        y_total_latency += y
        xs += x

        # Add horizontal lines every 100 percent
        ax1.axhline(y=100, color="k", linestyle="-", linewidth=3)
        ax1.axhline(y=75, color="k", linestyle="-", linewidth=1, alpha=0.5)
        ax1.axhline(y=50, color="k", linestyle="-", linewidth=1, alpha=0.5)
        ax1.axhline(y=25, color="k", linestyle="-", linewidth=1, alpha=0.5)

        ax1.set_xticks(x, ["Cloud", "Edge-Large", "Edge-Small", "Mist"])
        ax1.set_xlabel("Deployment")

        # Set y axis 1: load
        ax1.set_ylabel("System Load")
        ax1.yaxis.set_major_formatter(mtick.PercentFormatter())
        ax1.set_ylim(0, 100)
        ax1.set_yticks(np.arange(0, 125, 25))

        # Save
        t = time.strftime("%Y-%m-%d_%H:%M:%S", time.gmtime())
        plt.savefig("./logs/LargeDeployments_load_%s.pdf" % (t), bbox_inches="tight")

        self.y_load = y_total_load
        self.y_latency = y_total_latency

        self.plot2()

    def plot2(self):
        fig, ax = plt.subplots(figsize=(12, 6))

        colors = ["dimgray", "lightgray"]
        bars = ["Cloud", "Edge-Large", "Edge-Small", "Mist"]
        stacks = ["Processing", "Communication"]

        raw_vals = [run["latency_breakdown"] for run in self.runs]
        ax.bar(
            bars,
            list(list(zip(*raw_vals))[0]),
            color=colors[0],
            label=stacks[0],
        )
        ax.bar(
            bars,
            list(list(zip(*raw_vals))[1]),
            color=colors[1],
            label=stacks[1],
            bottom=list(list(zip(*raw_vals))[0]),
        )

        ax.set_ylabel("Time (ms)")
        ax.set_ylim(0, 400)
        ax.set_xlabel("Deployment")
        ax.legend(loc="upper left", framealpha=1.0)
        t = time.strftime("%Y-%m-%d_%H:%M:%S", time.gmtime())
        plt.savefig("./logs/LargeDeployments_breakdown_%s.pdf" % (t), bbox_inches="tight")

    def print_result(self):
        for i, config in enumerate(self.configs):
            logging.info(
                "Config: %15s | System Load: %4i%% | Latency: %10i ms | Comp: %10i ms | Comm: %10i ms"
                % (
                    config,
                    self.y_load[i],
                    self.y_latency[i],
                    self.runs[i]["latency_breakdown"][0],
                    self.runs[i]["latency_breakdown"][1],
                )
            )


def main(args):
    """Main function

    Args:
        args (Namespace): Argparse object
    """
    if args.experiment == "EndpointScaling":
        logging.info("Experiment: Scale endpoint connect to a single worker")
        exp = EndpointScaling(args.resume)
    elif args.experiment == "Deployments":
        logging.info("Experiment: Change deployments between cloud, edge, and local")
        pass
        exp = Deployments(args.resume)
    else:
        logging.error("Invalid experiment: %s" % (args.experiment))
        sys.exit()

    logging.info(exp)
    exp.generate()
    exp.check_resume()
    exp.run_commands()
    exp.parse_output()
    exp.plot()
    exp.print_result()


if __name__ == "__main__":
    """Get input arguments, and validate those arguments"""
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "experiment",
        choices=["EndpointScaling", "Deployments"],
        help="Experiment to replicate",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="increase verbosity level")
    parser.add_argument(
        "-r",
        "--resume",
        type=lambda s: datetime.datetime.strptime(s, "%Y-%m-%d_%H:%M:%S"),
        help='Resume a previous Experiment from datetime "YYYY-MM-DD_HH:mm:ss"',
    )
    args = parser.parse_args()

    enable_logging(args.verbose)
    main(args)
