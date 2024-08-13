import os
import sys

import traci
import traci.constants as tc

RED = [255, 0, 0]


def load_streets():
    streets = {}  # id: name
    for edge_id in traci.edge.getIDList():
        streets[edge_id] = traci.edge.getStreetName(edge_id)

    return streets


def avoid_edge(veh_id, edge_id):
    traci.vehicle.setAdaptedTraveltime(veh_id, edge_id, float('inf'))
    traci.vehicle.rerouteTraveltime(veh_id)


def prefer_edge(veh_id, edge_id):
    traci.vehicle.setAdaptedTraveltime(veh_id, edge_id, float('-inf'))
    traci.vehicle.rerouteTraveltime(veh_id)


def avoid_multiple(veh_id, edge_list):
    for edge in edge_list:
        avoid_edge(veh_id, edge)


def get_departed(filter_ids=None):
    if filter_ids is None:
        filter_ids = []
    newly_departed_ids = traci.simulation.getDepartedIDList()

    filtered_departed_ids = newly_departed_ids if len(filter_ids) == 0 else set(newly_departed_ids).intersection(
        filter_ids)

    return filtered_departed_ids


def set_vehicle_color(veh_id, color):
    traci.vehicle.setColor(veh_id, color)


def get_neighbouring_edges(edge_id, skip=None):
    if skip is None:
        skip = []

    id_list = []

    origin = traci.edge.getFromJunction(edge_id)
    destination = traci.edge.getToJunction(edge_id)

    id_list.extend(
        edge for edge in traci.junction.getIncomingEdges(origin) if
        'cluster' not in edge and '_' not in edge and edge not in skip)
    id_list.extend(
        edge for edge in traci.junction.getOutgoingEdges(origin) if
        'cluster' not in edge and '_' not in edge and edge not in skip)
    id_list.extend(
        edge for edge in traci.junction.getIncomingEdges(destination) if
        'cluster' not in edge and '_' not in edge and edge not in skip)
    id_list.extend(
        edge for edge in traci.junction.getOutgoingEdges(destination) if
        'cluster' not in edge and '_' not in edge and edge not in skip)

    return id_list


def get_all_neighbouring_edges(edge):
    id_list = []
    if isinstance(edge, list):
        for e in edge:
            id_list.extend(get_neighbouring_edges(e, skip=id_list))
    else:
        id_list = get_neighbouring_edges(edge)

    return list(set(id_list))


def end_simulation():
    if traci.isLoaded():
        traci.close()


def simulate(program, config, delay, closed_edges, _progress, task_id,
             description="",
             street_is_closed=False,
             keep_running=False,
             recorded_data=[],
             preferred_street=None,
             output_neighbouring_edges=False,
             log_duration=False,
             log_emissions=False,
             log_statistics=False,
             log_edgedata=False
             ):
    sys.stdout = open(os.devnull, 'w')

    try:
        command = [
            program,
            '-c', config,
            '--gui-settings-file', './config/viewSettings.xml',
            '--delay', str(delay),
            '--start',
            '--quit-on-end',
            '--no-warnings',
            '--no-step-log',
        ]
        if log_duration:
            command.append("--duration-log.statistics")
            command.append("--log")
            command.append(f"logs/{task_id}_logfile.txt")
        if log_emissions:
            command.append("--emission-output")
            command.append(f"logs/{task_id}_emissions.txt")
        if log_statistics:
            command.append("--statistic-output")
            command.append(f"logs/{task_id}_statistics.txt")
        if log_edgedata:
            command.append("--edgedata-output")
            command.append(f"logs/{task_id}_edgedata.txt")

        if traci.isLoaded():
            traci.load(command[1:])
        else:
            traci.start(command, stdout=open(os.devnull, 'w'))

        junction_id = traci.junction.getIDList()[0]
        variables = {
            "CO2": tc.VAR_CO2EMISSION,
            "CO": tc.VAR_COEMISSION,
            "HC": tc.VAR_HCEMISSION,
            "NOx": tc.VAR_NOXEMISSION,
            "PMx": tc.VAR_PMXEMISSION,
            "fuel": tc.VAR_FUELCONSUMPTION,
            "noise": tc.VAR_NOISEEMISSION,
        }
        traci.junction.subscribeContext(
            junction_id, tc.CMD_GET_VEHICLE_VARIABLE, 1000000,
            variables.values()
        )

        computed_data = {
            "CO2": 0,
            "CO": 0,
            "HC": 0,
            "NOx": 0,
            "PMx": 0,
            "fuel": 0,
            "noise": 0,
        }

        output = {
            "id": task_id,
            "pref_street": preferred_street,
        }

        if preferred_street is not None:
            preferred_street_name = load_streets().get(preferred_street)
            output['pref_street_name'] = preferred_street_name
            task_description = f'{preferred_street_name} ({preferred_street})'
        else:
            task_description = description

        if output_neighbouring_edges:
            output['neighbours'] = []
            for edge in closed_edges:
                output['neighbours'].extend(get_all_neighbouring_edges(edge))

        simulated = 0
        total = 0
        removed = []
        affected = []

        step_length = traci.simulation.getDeltaT()
        n_steps = 0

        if street_is_closed:
            for edge in closed_edges:
                for lane in range(traci.edge.getLaneNumber(edge)):
                    traci.lane.setAllowed(f'{edge}_{lane}', "authority")  # close the edge to regular traffic

        while traci.simulation.getMinExpectedNumber() > 0:
            if street_is_closed:
                for edge in closed_edges:
                    for vehId in get_departed():
                        if vehId in removed:
                            continue

                        route = traci.vehicle.getRoute(vehId)
                        if edge in route:
                            if route[0] == edge:
                                # print(f"Removed vehicle {vehId} because route started with closed edge")
                                traci.vehicle.remove(vehId)
                                removed.append(vehId)
                            elif route[-1] == edge:
                                # print(f"Removed vehicle {vehId} because route ended with closed edge")
                                traci.vehicle.remove(vehId)
                                removed.append(vehId)
                            else:
                                set_vehicle_color(vehId, RED)
                                prefer_edge(vehId, preferred_street)

                                if vehId not in affected:
                                    affected.append(vehId)

                                # traci.vehicle.setVia(vehId, preferred_street)
                                # traci.vehicle.rerouteTraveltime(vehId)
                                # avoid_edge(vehId, edge)
                        else:
                            if vehId not in affected:
                                set_vehicle_color(vehId, [0, 0, 0, 0])  # draws only cars affected by street closure

            traci.simulationStep()

            sub_results = traci.junction.getContextSubscriptionResults(junction_id)
            if sub_results:
                for (k, v) in variables.items():
                    new_values = [d[v] for d in sub_results.values()]
                    new_mean = sum(new_values) / len(new_values)
                    computed_data[k] = (n_steps * computed_data[k] + new_mean) / (n_steps + 1)

            n_steps += 1

            simulated += traci.simulation.getArrivedNumber()
            total += traci.simulation.getLoadedNumber()
            if _progress is not None and task_id is not None:
                _progress[task_id] = {"description": task_description,
                                      "progress": simulated, "total": total}

        output["duration"] = traci.simulation.getParameter("", "device.tripinfo.duration")
        output['routeLength'] = traci.simulation.getParameter("", "device.tripinfo.routeLength")
        output['departDelay'] = traci.simulation.getParameter("", "device.tripinfo.departDelay")
        output['waitingTime'] = traci.simulation.getParameter("", "device.tripinfo.waitingTime")
        output['speed'] = traci.simulation.getParameter("", "device.tripinfo.speed")
        output['timeloss'] = traci.simulation.getParameter("", "device.tripinfo.timeLoss")
        output['teleports'] = traci.simulation.getParameter("", "stats.teleports.total")
        output['totalTime'] = n_steps * step_length

        for d in computed_data:
            output[d] = computed_data[d]

        if not keep_running:
            end_simulation()

    finally:
        sys.stdout = sys.__stdout__

    return output
