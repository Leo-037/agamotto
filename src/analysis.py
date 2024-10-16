import itertools
import os
import sumolib


def get_net_from_cfg(config):
    net_file_name = list(sumolib.xml.parse(config, 'net-file'))[0].value
    return os.path.join(os.path.split(config)[0], net_file_name)


def get_options(net, closed_id, options, closed_edges):
    closed = net.getEdge(closed_id)

    # all edges that are in a 'connection' to the closed one, excluding those that are also closed
    incoming = [i for i in closed.getIncoming() if i.getID() not in closed_edges]

    for connection in incoming:
        # take all alternatives to closed edges
        alternatives = [o.getID() for o in connection.getOutgoing() if o.getID() not in closed_edges]

        connection_id = connection.getID()

        if len(alternatives) > 0:  # for this edge there are options that are not the closed edge
            current_alts = options.setdefault(connection_id, [])  # create if key doesn't exist
            for alt in alternatives:
                if alt not in current_alts:
                    options[connection_id].append(alt)
        else:
            # the edge is only connected to closed ones: I need to go back an edge
            if connection_id not in closed_edges:
                closed_edges.append(connection_id)  # I can now treat this edge as closed
                get_options(net, connection_id, options, closed_edges)


def analyze_network(net_file, closed_edges):
    options = {}  # {'edge_id': ['opzione1', 'opzione2'],}

    net = sumolib.net.readNet(net_file)
    for edge in closed_edges:
        get_options(net, edge, options, closed_edges)

    return options


def from_destination_pov(options):
    new = {}
    for origin, destinations in options.items():
        for dest in destinations:
            if dest in new:
                new[dest].append(origin)
            else:
                new[dest] = [origin]

    return new


def generate_combinations(options):
    keys = list(options.keys())
    lists = list(options.values())

    # Generate all combinations
    combinations = itertools.product(*lists)

    # Convert combinations into a list of dictionaries
    return [[{'origin': key, 'destination': value} for key, value in zip(keys, combination)]
            for combination in combinations]


def pretty_combination(combination):
    destinations = {}
    for od in combination:
        origin = od['origin']
        destination = od['destination']
        if destination in destinations:
            destinations[destination].append(origin)
        else:
            destinations[destination] = [origin]

    result = ""
    for dest in destinations:
        for origin in destinations[dest]:
            result += f"[blue]{origin} "
        result += f"[bold default]-> [green]{dest} [bold default]/ "
    return result[:-2]
