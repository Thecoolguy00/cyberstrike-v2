#master.py
import json, time
from pathlib import Path
from data_graph import graph
from graph_tools import save_data, extract_text
from config import TYPE, TARGET, type_list, has_state_file

if TYPE in has_state_file:
    TASK_FILE=f"{TYPE}_task.json"
    STATE_FILE=f"{TYPE}_state_task_{TARGET.replace(' ','_')}.json"

def init_state_tasks():
    if Path(STATE_FILE).exists():
        return
    
    static=json.loads(Path(TASK_FILE).read_text(encoding="utf-8"))
    state={
        "target":TARGET,
        "tasks":[
            {
                "id":t["id"],
                "description":t["description"],
                "status":"pending"
            }
            for t in static["tasks"]
        ],
    }

    Path(STATE_FILE).write_text(json.dumps(state, indent=2), encoding="utf-8")

def load_state():
    data=json.loads(Path(STATE_FILE).read_text(encoding="utf-8"))

    return {t["id"]: t for t in data["tasks"]}


def save_state(tasks):
    Path(STATE_FILE).write_text(
        json.dumps(
            {"target":TARGET, "tasks": list(tasks.values())},
            indent=2,
        ),
        encoding="utf-8",
    )

def run_master():
    print("[MASTER] Starting")

    if TYPE=="aggregrate":
        result=graph.invoke(
            {
                "task":TYPE,
                "target":TARGET,
            }
        )
        raw = result["messages"][-1].content
        final_text = extract_text(raw)
        print(f"[MASTER] Tool[save_data]")
        save_data(final_text, task_id=TYPE, target=TARGET)

        print("[MASTER] All tasks processed")

        return


    init_state_tasks()
    tasks=load_state()

    for task_id, task in tasks.items():
        if task["status"]=="done":
            continue

        print(f"[MASTER] Dispatching task -> {task_id}")
        task["status"]="in_progress"
        save_state(tasks)

        try:
            result=graph.invoke(
                {
                    "task":task["description"],
                    "target":TARGET,
                }
            )
            raw = result["messages"][-1].content
            final_text = extract_text(raw)
            print(f"[MASTER] Tool[save_data]")
            save_data(final_text, task_id, target=TARGET)

            task["status"]="done"
            print(f"[MASTER] Task {task_id} completed")
            # print(f"[MASTER] Sleeping for 15s")
            # time.sleep(15)

        
        except Exception as e:
            task["status"]="failed"
            print(f"[MASTER] Task {task_id} crashed: ",e)
            # print(f"[MASTER] Sleeping for 15s")
            # time.sleep(15)

        save_state(tasks)
    
    print("[MASTER] All tasks processed")


if __name__=="__main__":
    run_master()