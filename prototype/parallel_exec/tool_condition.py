def multi_router(state):
    last = state["messages"][-1]

    if not getattr(last, "tool_calls", None):
        return END  # no tools called → finish

    routes = []
    for tc in last.tool_calls:
        routes.append(tc["name"])

    return routes
