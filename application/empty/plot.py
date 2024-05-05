"""Create plots for the empty application"""

import logging
import math

import numpy as np

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator


def plot_status(status, timestamp):
    """Print and plot controlplane data from external observations

    Args:
        status (list(list(str)), optional): Status of started Kubernetes pods over time
        timestamp (time): Global timestamp used to save all files of this run
    """
    for stat in status:
        logging.debug(stat)

    # Make sure matplotlib doesn't inherit our own logging level
    logging.getLogger("matplotlib").setLevel("WARNING")

    # From: https://docs.openstack.org/developer/performance-docs/test_results/
    #           container_cluster_systems/kubernetes/density/index.html
    _, ax1 = plt.subplots(figsize=(12, 6))

    # Re-format data
    times = [s["time"] for s in status]
    arriving = [s["Arriving"] for s in status]
    pending = [s["Pending"] for s in status]
    containercreating = [s["ContainerCreating"] for s in status]
    running = [s["Running"] for s in status]
    succeeded = [s["Succeeded"] for s in status]

    categories = []
    results = []
    if sum(arriving) > 0:
        categories.append("Arriving")
        results.append(arriving)
    if sum(pending) > 0:
        categories.append("Pending")
        results.append(pending)
    if sum(containercreating) > 0:
        categories.append("ContainerCreating")
        results.append(containercreating)
    if sum(running) > 0:
        categories.append("Running")
        results.append(running)
    if sum(succeeded) > 0:
        categories.append("Succeeded")
        results.append(succeeded)

    colors = {
        "Arriving": "#cc0000",
        "Pending": "#ffb624",
        "ContainerCreating": "#ebeb00",
        "Running": "#50c878",
        "Succeeded": "#a366ff",
    }

    cs = [colors[cat] for cat in categories]
    ax1.stackplot(times, results, colors=cs, step="post")

    ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.invert_yaxis()
    ax1.grid(True)

    # Set y axis details
    total_pods = sum(status[0][cat] for cat in categories)
    ax1.set_ylabel("Pods")
    ax1.set_ylim(0, total_pods)

    # Set x axis details
    # Note: If the pod is deployed in < 1 second, there is only one status entry with time = 0.0
    #       You can't set xlim to [0 - 0], so we have to set it to at least 1.0
    ax1.set_xlabel("Time (s)")
    ax1.set_xlim(0, max(status[-1]["time"], 1.0))

    # add legend
    patches = [mpatches.Patch(color=c) for c in cs]
    texts = categories
    ax1.legend(patches, texts, loc="upper right")

    # Save plot
    plt.savefig("./logs/%s_breakdown.pdf" % (timestamp), bbox_inches="tight")


def plot_control(df, timestamp, xmax=None, ymax=None, xinter=None, yinter=None):
    """Plot controlplane data from the source code

    Phases:
    1: Create workload        [starttime, manage_job]
      - Starts when the user executes KubeCTL
          - Times in Continuum
      - Ends when the resource controller (e.g., job controller)
        receives the workload resource object
          - Source code 0028
      - In between, the APIserver creates the workload resource object in the datastore
        and the appropiate resource controller notices that resource has been created

    2: Unpack workload        [manage_job, pod_object]
      - Ends right before a pod is created for a particular workload instance
          - Source code 0277
      - In between, workload-wide stuff is checked like permissions, and the object is
        unpacked into workload instances if parallelism is used. Each instance is
        treated seperately from here on.

    3: Pod object creation    [pod_object, scheduler_queue]
      - Ends right before pod is added to the scheduling queue
          - Source code 0124
      - In between, a pod is created for a workload instance, is written to the datastore
        via the APIserver, which the scheduler notices and adds to its scheduling queue

    4: Scheduling             [scheduler_queue, pod_create]
      - Ends when the container runtime on a worker starts creating resources for this pod
      - In between, the pod is added to the scheduling queue, the scheduler attempts to
        and eventually successfully schedules the pod onto a worker node, and writes
        the status update back to the datastore via the APIserver

    5: Pod creation           [pod_create, container_create]
      - Ends when containers inside the pod are starting to be created
      - In between, the kubelet notices a pod object in the datastore has been assigned to
        the worker node of that kubelet, and calls various OS-level software packages and
        the container runtime to create a pod abstraction, including process+network namespaces

    6: Container creation     [container_create, app_start]
      - Ends when the application in the container prints output
      - In between, all containers inside the pod are being created, the pod and containers are
        being started and the code inside the container starts executing

    7: Application run        [app_start, >]
      - Application code inside the container is running

    Args:
        df (DataFrame): Pandas dataframe object with parsed timestamps per category
        timestamp (time): Global timestamp used to save all files of this run
        xmax (bool): Optional. Set the xmax of the plot by hand. Defaults to None.
        ymax (bool): Optional. Set the ymax of the plot by hand. Defaults to None.
    """
    plt.rcParams.update({"font.size": 20})
    fig, ax1 = plt.subplots(figsize=(12, 4))

    bar_height = 1.1

    df_plot = df.copy(deep=True)
    df_plot = df_plot[
        [
            "controller_read_workload (s)", #0028
            "controller_unpacked_workload (s)", #0277
            "scheduler_read_pod (s)",   #0124
            "kubelet_pod_received (s)", #0500
            "kubelet_applied_sandbox (s)",  #0514
            "started_application (s)",
        ]
    ]
    y = [*range(len(df_plot["started_application (s)"]))]

    left = [0 for _ in range(len(y))]

    colors = {
        "S1: CWO end:0028": "#6929c4",
        "S2: UWO end:0277": "#1192e8",
        "S3: CPO end:0124": "#005d5d",
        "S4: SP end:0500": "#9f1853",
        "S5: CP end:0514": "#fa4d56",
        "S6: CC": "#570408",
        "Deployed": "#198038",
    }
    cs = list(colors.values())

    for column, c in zip(df_plot, cs):
        plt.barh(y, df_plot[column] - left, color=c, left=left, align="edge", height=bar_height)
        left = df_plot[column]

    # Calculate final bar to make all bars the same length
    max_time = df_plot["started_application (s)"].max()
    if xmax is not None and xmax != max_time:
        # Or fill to some custom xmax
        max_time = xmax
    elif xmax is None and max_time < 1.0:
        # xmax should be at least 1.0
        max_time = 1.0

    left = df_plot["started_application (s)"]
    diff = [max_time - l for l in left]
    plt.barh(y, diff, color=cs[-1], left=left, align="edge", height=bar_height)

    # Set plot details
    ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.grid(True)

    # Set y axis details
    ax1.set_ylabel("Pods")
    y_max = len(y)
    if ymax:
        y_max = ymax

    ax1.set_ylim(0, y_max)

    # Set x axis details
    ax1.set_xlabel("Time (s)")
    x_max = max(1.0, max_time)
    if xmax:
        x_max = xmax

    ax1.set_xlim(0, x_max)

    # Set x/y ticks if argument passed
    if xinter:
        ax1.set_xticks(np.arange(0, x_max + 0.1, xinter))
    if yinter:
        ax1.set_yticks(np.arange(0, y_max + 0.1, yinter))

    # add legend
    patches = []
    for c in cs:
        patches.append(mpatches.Patch(facecolor=c, edgecolor="k"))

    texts = colors.keys()
    ax1.legend(patches, texts, loc="lower right", fontsize="16")

    # Save plot
    plt.savefig("./logs/%s_breakdown_intern.pdf" % (timestamp), bbox_inches="tight")
    plt.close(fig)


def plot_p56(df, timestamp, xmax=None, ymax=None, xinter=None, yinter=None, width=20, height=5):
    """Plot controlplane data from the source code

    Phases:
    1: Start Pod
        - Starts:   C_start_pod     -> 0500
        - Ends:     C_volume_mount  -> 0504
    2. Volume mount
        - Ends:     C_apply_sandbox -> 0511
    3. Create Sandbox
        - Ends:     C_start_cont    -> 0521
    4. Start container
        - Ends:     C_pod_done      -> 0515 Pod is done
    5. Start application
        - Ends:     created_container (s)

    Args:
        df (DataFrame): Pandas dataframe object with parsed timestamps per category
        timestamp (time): Global timestamp used to save all files of this run
        xmax (bool): Optional. Set the xmax of the plot by hand. Defaults to None.
        ymax (bool): Optional. Set the ymax of the plot by hand. Defaults to None.
    """
    plt.rcParams.update({"font.size": 20})
    fig, ax1 = plt.subplots(figsize=(width, height))

    bar_height = 1.1

    df_plot = df.copy(deep=True)
    df_plot = df_plot[
        [
            "kubelet_pod_received (s)", #0500
            "kubelet_created_cgroup (s)", #0504
            "kubelet_mounted_volume (s)", #0505
            "kubelet_applied_sandbox (s)", #0514
            "kubelet_created_container (s)", #0517
            "started_application (s)",
        ]
    ]

    df_plot = df_plot.sort_values(by=["started_application (s)"])
    df_plot.to_csv("./logs/%s_sort_dataframe_56.csv" % timestamp, index=False, encoding="utf-8")

    y = [*range(len(df_plot["started_application (s)"]))]

    left = [0 for _ in range(len(y))]

    colors = {
        "EMPTY": "#ffffff", 
        r"$T_{cg} + T_{nn}$ 500-504": "#6929c4",
        r"$\sum_{i=0}^{V} T_{mv,i}$ 504-505": "#1192e8",
        r"$T_{cs}$ 505-514": "#005d5d",
        r"$\sum_{i=0}^{C} T_{cc,i}$ 514-517": "#9f1853",
        r"$\sum_{j=0}^{C} T_{sc,j}$": "#fa4d56",
        "Deployed": "#ffffff",
    }
    cs = list(colors.values())

    for column, c in zip(df_plot, cs):
        plt.barh(y, df_plot[column] - left, color=c, left=left, align="edge", height=bar_height)
        left = df_plot[column]

    # Calculate final bar to make all bars the same length
    max_time = df_plot["started_application (s)"].max()
    left = df_plot["started_application (s)"]
    diff = [max_time - l for l in left]
    plt.barh(y, diff, color=cs[-1], left=left, align="edge", height=bar_height)

    # Set plot details
    ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.grid(True)

    # Set y axis details
    ax1.set_ylabel("Pods")
    y_max = len(y)
    if ymax:
        y_max = ymax

    ax1.set_ylim(0, y_max)

    # Set x axis details
    ax1.set_xlabel("Time (s)")
    x_max = max(1.0, max_time)
    if xmax:
        x_max = xmax

    ax1.set_xlim(0, x_max)

    # Set x/y ticks if argument passed
    if xinter:
        ax1.set_xticks(np.arange(0, x_max + 0.1, xinter))
    if yinter:
        ax1.set_yticks(np.arange(0, y_max + 0.1, yinter))

    # add legend
    patches = []
    for c in cs[1:-1]:
        patches.append(mpatches.Patch(facecolor=c, edgecolor="k"))

    colors.pop("EMPTY")
    colors.pop("Deployed")
    texts = colors.keys()
    ax1.legend(patches, texts, loc="lower left", fontsize="16")

    # Save plot
    plt.savefig("./logs/%s_breakdown_intern_P56.pdf" % (timestamp), bbox_inches="tight")
    plt.close(fig)

def plot_p57(df, timestamp, xmax=None, ymax=None, xinter=None, yinter=None, width=500, height=5):
    """Plot controlplane data from the source code

    Phases:
    1: Start Pod
        - Starts:   C_start_pod     -> 0500
        - Ends:     C_volume_mount  -> 0504
    2. Volume mount
        - Ends:     C_apply_sandbox -> 0511
    3. Create Sandbox
        - Ends:     C_start_cont    -> 0521
    4. Start container
        - Ends:     C_pod_done      -> 0515 Pod is done
    5. Start application
        - Ends:     created_container (s)

    Args:
        df (DataFrame): Pandas dataframe object with parsed timestamps per category
        timestamp (time): Global timestamp used to save all files of this run
        xmax (bool): Optional. Set the xmax of the plot by hand. Defaults to None.
        ymax (bool): Optional. Set the ymax of the plot by hand. Defaults to None.
    """
    plt.rcParams.update({"font.size": 20})
    fig, ax1 = plt.subplots(figsize=(width, height))

    bar_height = 1.1

    df_plot = df.copy(deep=True)
    df_plot = df_plot[
        [
            "kubelet_pod_received (s)", #0500
            # "kubelet_created_cgroup (s)", #0504
            # "kubelet_mounted_volume (s)", #0505
            # "kubelet_applied_sandbox (s)", #0514
            # "kubelet_created_container (s)", #0517
            "started_application (s)",
            # "kubelet_0502 (s)",
            # "kubelet_0503 (s)",
            # "kubelet_0506 (s)",
            # "kubelet_0507 (s)",
            # "kubelet_0508 (s)",
            # "kubelet_0509 (s)",
            # "kubelet_0510 (s)",
            # "kubelet_0511 (s)",
            # "kubelet_0512 (s)",
            # "kubelet_0513 (s)",
            # "kubelet_0515 (s)",
            # "kubelet_0516 (s)",
            # "kubelet_0518 (s)",
            # "kubelet_0519 (s)",
            # "kubelet_0520 (s)",
            # "kubelet_0521 (s)",
            # "kubelet_0522 (s)",
            # "kubelet_0523 (s)",
            # "kubelet_0540 (s)",
            # "kubelet_0541 (s)",
            # "kubelet_0542 (s)",
            # "kubelet_0555 (s)",
            # "kubelet_0556 (s)",
            # "kubelet_0557 (s)",
            # "kubelet_0558 (s)",
            # "kubelet_0559 (s)",
            # "kubelet_0560 (s)",
        # "0601",
        "0602",
        # "0603",
        # "0604",
        "0605",
        # "0606",
        # "0641",
        "0642",
        # "0643",
        # "0644",
        "0645",
        # "0646",
        "0647",
        # "0648",
        # "0611",
        # "0612",
        # "0613",
        # "0614",
        # "0631",
        # "0632",
        # "0633",
        "0634",
        "0635",
        ]
    ]

    # df_plot.to_csv("./logs/%s_unsort_dataframe.csv" % timestamp, index=False, encoding="utf-8")
    df_plot = df_plot.sort_values(by=["started_application (s)"])
    df_plot = df_plot.sort_values(by=df.first_valid_index(), axis=1)
    df_plot.to_csv("./logs/%s_sort_dataframe_57.csv" % timestamp, index=False, encoding="utf-8")

    y = [*range(len(df_plot["started_application (s)"]))]

    left = [0 for _ in range(len(y))]

    new_colors = {
        "kubelet_pod_received (s)": ["EMPTY", "#ffffff"],   #0500
        "kubelet_created_cgroup (s)": [r"$T_{cg} + T_{nn}$ 0504", "#6929c4"],    #0504
        "kubelet_mounted_volume (s)": [r"$\sum_{i=0}^{V} T_{mv,i}$ 0505", "#1192e8"],    #0505
        "kubelet_applied_sandbox (s)": [r"$T_{cs}$ 0514", "#005d5d"], #0514
        "kubelet_created_container (s)": [r"$\sum_{i=0}^{C} T_{cc,i}$ 0517", "#9f1853"], #0517
        "started_application (s)": [r"$\sum_{j=0}^{C} T_{sc,j}$", "#fa4d56"],

        "kubelet_0502 (s)": ["end:0502", "#9980ff"],
        "kubelet_0503 (s)": ["end:0503", "#cc0000"],
        "kubelet_0506 (s)": ["end:0506", "#993333"],
        "kubelet_0507 (s)": ["end:0507", "#1aa3ff"],
        "kubelet_0508 (s)": ["end:0508", "#cc3300"],
        "kubelet_0509 (s)": ["end:0509", "#ffcc99"],
        "kubelet_0510 (s)": ["end:0510", "#336600"],
        "kubelet_0511 (s)": ["end:0511", "#cc0033"],
        "kubelet_0512 (s)": ["end:0512", "#00CED1"],
        "kubelet_0513 (s)": ["end:0513", "#ff751a"],
        "kubelet_0515 (s)": ["end:0515", "#ff6600"],
        "kubelet_0516 (s)": ["end:0516", "#660000"],
        "kubelet_0518 (s)": ["end:0518", "#B3BF6F"],
        "kubelet_0519 (s)": ["end:0519", "#cc0066"],
        "kubelet_0520 (s)": ["end:0520", "#ff944d"],
        "kubelet_0521 (s)": ["end:0521", "#ffe6cc"],
        "kubelet_0522 (s)": ["end:0522", "#99ccff"],
        "kubelet_0523 (s)": ["end:0523", "#23F23C"],
        "kubelet_0540 (s)": ["end:0540", "#ffb380"],
        "kubelet_0541 (s)": ["end:0541", "#66cc66"],
        "kubelet_0542 (s)": ["end:0542", "#e6ac00"],
        "kubelet_0555 (s)": ["end:0555", "#ff3300"],
        "kubelet_0556 (s)": ["end:0556", "#ffdbb0"],
        "kubelet_0557 (s)": ["end:0557", "#ff8533"],
        "kubelet_0558 (s)": ["end:0558", "#8b4513"],
        "kubelet_0559 (s)": ["end:0559", "#23F23C"],
        "kubelet_0560 (s)": ["end:0560", "#ff1a75"],

        "0601": ["0601:SyncPod:start", "#9980ff"],
        "0602": ["0602:SyncPod:cgroups:done", "#cc0000"],
        "0603": ["0603:SyncPod:CreateMirrorPod:done", "#993333"],
        "0604": ["0604:SyncPod:makePodDataDirs:done", "#cc9900"],
        "0605": ["0605:SyncPod:WaitForAttachAndMount:done", "#1aa3ff"],
        "0606": ["0606:SyncPod:done", "#cc3300"],
        "0641": ["0641:startContainer:start", "#ffcc99"],
        "0642": ["0642:startContainer:EnsureImageExists:done", "#ff1a75"],
        "0643": ["0643:startContainer:generateContainerConfig:done", "#cc0033"],
        "0644": ["0644:startContainer:PreCreateContainer:done", "#ff751a"],
        "0645": ["0645:startContainer:CreateContainer:done", "#00CED1"],
        "0646": ["0646:startContainer:PreStartContainer:done", "#660000"],
        "0647": ["0647:startContainer:StartContainer:done", "#B3BF6F"],
        "0648": ["0648:startContainer:done", "#cc0066"],
        "0611": ["0611:SyncPod:start ", "#ff944d"],
        "0612": ["0612:SyncPod:CreateSandbox:done", "#99ccff"],
        "0613": ["0613:SyncPod:generatePodSandboxConfig:done", "#23F23C"],
        "0614": ["0614:SyncPod:done", "#ffb380"],
        "0631": ["0631:createPodSandbox:start", "#66cc66"],
        "0632": ["0632:createPodSandbox:generatePodSandboxConfig:done", "#e6ac00"],
        "0633": ["0633:createPodSandbox:MkdirAll:done", "#ff3300"],
        "0634": ["0634:createPodSandbox:LookupRuntimeHandler:done", "#ffdbb0"],
        "0635": ["0635:createPodSandbox:RunPodSandbox:done", "#ff8533"],
    }
    used_colors = {}

    for column in df_plot:
        plt.barh(y, df_plot[column] - left, color=new_colors[column][1], left=left, align="edge", height=bar_height)
        left = df_plot[column]
        used_colors[new_colors[column][0]] = new_colors[column][1]

    cs = list(used_colors.values())

    # Calculate final bar to make all bars the same length
    max_time = df_plot["started_application (s)"].max()
    left = df_plot["started_application (s)"]
    diff = [max_time - l for l in left]
    plt.barh(y, diff, color="#ffffff", left=left, align="edge", height=bar_height)

    # Set plot details
    ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.grid(True)

    # Set y axis details
    ax1.set_ylabel("Pods")

    y_max = len(y)
    if ymax:
        y_max = ymax

    ax1.set_ylim(0, y_max)

    # Set x axis details
    ax1.set_xlabel("Time (s)")
    x_max = max(1.0, max_time)
    if xmax:
        x_max = xmax

    ax1.set_xlim(0, x_max)
    #set xticks
    xticks = np.arange(0, x_max, min([0.1, 1, 10], key=lambda x: abs(x - x_max/10)))
    ax1.set_xticks(xticks)

    # Set x/y ticks if argument passed
    if xinter:
        ax1.set_xticks(np.arange(0, x_max + 0.1, xinter))
    if yinter:
        ax1.set_yticks(np.arange(0, y_max + 0.1, yinter))

    # add legend
    patches = []
    for c in cs[1:]:
        patches.append(mpatches.Patch(facecolor=c, edgecolor="k"))

    used_colors.pop("EMPTY")
    texts = used_colors.keys()
    ax1.legend(patches, texts, loc="best", fontsize=height*2)

    # Save plot
    plt.savefig("./logs/%s_breakdown_intern_P57_%s.pdf" % (timestamp, width), bbox_inches="tight")
    plt.close(fig)

def plot_resources(df, timestamp, xmax=None, ymax=None, xinter=None, yinter=None):
    """Plot resource utilization data

    Args:
        df (DataFrame): Pandas dataframe object with parsed timestamps per category
        timestamp (time): Global timestamp used to save all files of this run
        xmax (bool): Optional. Set the xmax of the plot by hand. Defaults to None.
        ymax (bool): Optional. Set the ymax of the plot by hand. Defaults to None.
    """
    plot_resources_kube(df[0], timestamp, xmax, ymax, xinter, yinter)
    plot_resources_os(df[1], timestamp, xmax, ymax, xinter, yinter)


def plot_resources_kube(df, timestamp, xmax=None, ymax=None, xinter=None, yinter=None):
    """Plot resources based on kubectl top command

    Args:
        df (DataFrame): Pandas dataframe object with parsed timestamps per category
        timestamp (time): Global timestamp used to save all files of this run
        xmax (bool): Optional. Set the xmax of the plot by hand. Defaults to None.
        ymax (bool): Optional. Set the ymax of the plot by hand. Defaults to None.
    """
    # Create one plot for cpu and one for memory
    plt.rcParams.update({"font.size": 20})
    fig, ax1 = plt.subplots(figsize=(12, 4))

    for column in df.columns:
        if "_cpu" in column:
            ax1.plot(df["Time (s)"], df[column], label=column)

    ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.grid(True)

    # Set y axis details
    ax1.set_ylabel("CPU Usage (millicpu)")
    y_max = math.ceil(df.filter(like="_cpu").values.max() * 1.1)
    if ymax:
        y_max = ymax

    ax1.set_ylim(0, y_max)

    # Set x axis details
    ax1.set_xlabel("Time (s)")
    x_max = df["Time (s)"].values.max()
    if ymax:
        x_max = xmax

    ax1.set_xlim(0, x_max)

    # Set x/y ticks if argument passed
    if xinter:
        ax1.set_xticks(np.arange(0, x_max + 0.1, xinter))
    if yinter:
        ax1.set_yticks(np.arange(0, y_max + 0.1, yinter))

    # add legend
    ax1.legend(loc="best", fontsize="16")

    plt.savefig("./logs/%s_resources_cpu.pdf" % (timestamp), bbox_inches="tight")
    plt.close(fig)

    # ------------------------------
    # Now for memory
    fig, ax1 = plt.subplots(figsize=(12, 4))

    for column in df.columns:
        if "_memory" in column:
            ax1.plot(df["Time (s)"], df[column], label=column)

    ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.grid(True)

    # Set y axis details
    ax1.set_ylabel("Memory Usage (MB)")
    y_max = math.ceil(df.filter(like="_memory").values.max() * 1.1)
    if ymax:
        y_max = ymax

    ax1.set_ylim(0, y_max)

    # Set x axis details
    ax1.set_xlabel("Time (s)")
    x_max = df["Time (s)"].values.max()
    if ymax:
        x_max = xmax

    ax1.set_xlim(0, x_max)

    # Set x/y ticks if argument passed
    if xinter:
        ax1.set_xticks(np.arange(0, x_max + 0.1, xinter))
    if yinter:
        ax1.set_yticks(np.arange(0, y_max + 0.1, yinter))

    # add legend
    ax1.legend(loc="best", fontsize="16")

    plt.savefig("./logs/%s_resources_memory.pdf" % (timestamp), bbox_inches="tight")
    plt.close(fig)


def plot_resources_os(df, timestamp, xmax=None, ymax=None, xinter=None, yinter=None):
    """Plot resources based on os-level resource metric commands

    Args:
        df (DataFrame): Pandas dataframe object with parsed timestamps per category
        timestamp (time): Global timestamp used to save all files of this run
        xmax (bool): Optional. Set the xmax of the plot by hand. Defaults to None.
        ymax (bool): Optional. Set the ymax of the plot by hand. Defaults to None.
    """
    plt.rcParams.update({"font.size": 20})
    fig, ax1 = plt.subplots(figsize=(12, 4))

    for column in df.columns:
        if "cpu-used" in column:
            name = column
            if "controller" in column:
                name = "Control Plane"
            else:
                name = "Worker Node " + column.split("cloud")[1].split(" (")[0]
            ax1.plot(df["Time (s)"], df[column], label=name)

    ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.grid(True)

    # Set y axis details
    ax1.set_ylabel("CPU Utilization (%)")
    y_max = 100
    if ymax:
        y_max = ymax

    ax1.set_ylim(0, y_max)

    # Set x axis details
    ax1.set_xlabel("Time (s)")
    x_max = df["Time (s)"].values.max()
    if xmax:
        x_max = xmax

    ax1.set_xlim(0, x_max)

    # Set x/y ticks if argument passed
    if xinter:
        ax1.set_xticks(np.arange(0, x_max + 0.1, xinter))
    if yinter:
        ax1.set_yticks(np.arange(0, y_max + 0.1, yinter))

    # add legend
    ax1.legend(loc="best", fontsize="16")

    plt.savefig("./logs/%s_resources_os_cpu.pdf" % (timestamp), bbox_inches="tight")
    plt.close(fig)

    # ------------------------------
    # Now for memory
    fig, ax1 = plt.subplots(figsize=(12, 4))

    for column in df.columns:
        if "memory-used" in column:
            name = column
            if "controller" in column:
                name = "Control Plane"
            else:
                name = "Worker Node " + column.split("cloud")[1].split(" (")[0]
            ax1.plot(df["Time (s)"], df[column], label=name)

    ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.grid(True)

    # Set y axis details
    ax1.set_ylabel("Memory Utilization (%)")
    y_max = 100
    if ymax:
        y_max = ymax

    ax1.set_ylim(0, y_max)

    # Set x axis details
    ax1.set_xlabel("Time (s)")
    x_max = df["Time (s)"].values.max()
    if xmax:
        x_max = xmax

    ax1.set_xlim(0, x_max)

    # Set x/y ticks if argument passed
    if xinter:
        ax1.set_xticks(np.arange(0, x_max + 0.1, xinter))
    if yinter:
        ax1.set_yticks(np.arange(0, y_max + 0.1, yinter))

    # add legend
    ax1.legend(loc="best", fontsize="16")

    plt.savefig("./logs/%s_resources_os_memory.pdf" % (timestamp), bbox_inches="tight")
    plt.close(fig)
