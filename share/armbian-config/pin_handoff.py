"""Resolve explicit header owner handoffs against the selected board catalog."""


def selection(target, catalog):
    key, *ports = target.split("+")
    route = catalog.ROUTES.get(key)
    if route is None:
        raise ValueError("INVALID: Неизвестный маршрут гребёнки")
    if not ports:
        return route, ()
    owners = set(ports)
    if (not route.can_take_pins or route.port in owners or
            len(ports) != len(owners) or not owners.issubset(catalog.RELEASES)):
        raise ValueError("INVALID: Недопустимый список владельцев для этого маршрута")
    return route, tuple(catalog.RELEASES[port] for port in sorted(ports))


def transition_label(route, releases):
    names = {"camera": "камеру VIN", "pinctrl-test": "тестовый драйвер PIO"}
    owners = [names.get(r.port, r.port.upper().replace("I2C", "I²C")) for r in releases]
    if len(owners) == 1:
        return f"Отключить {owners[0]} и включить {route.label}"
    owner_list = ", ".join(owners[:-1]) + " и " + owners[-1]
    return f"Отключить {owner_list}, затем включить {route.label}"


def owners_on_route(route, current, candidate):
    pins = {row["pin"] for row in candidate if any(o["path"] == route.path for o in row["owners"])}
    return {o["path"] for row in current if row["pin"] in pins for o in row["owners"] if o["path"] != route.path}


def conflicting_releases(route, current, candidate, catalog):
    if not route.can_take_pins:
        return ()
    conflicts = owners_on_route(route, candidate, candidate)
    if not conflicts or not conflicts <= owners_on_route(route, current, candidate):
        return ()
    ports = sorted(port for port, release in catalog.RELEASES.items() if release.path in conflicts)
    releases = tuple(catalog.RELEASES[port] for port in ports)
    if {r.path for r in releases} != conflicts:
        return ()
    return releases
