"""
background_tasks.py - handles bacground execution of long-running tools
like gobuster, nmap(-p-), nikto, etc.
each task runs seperately, logs to a file, and can be checked later
"""

import os,time,subprocess,signal,json
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import asyncio

class BackgroundTaskManager:
    """Runs and monitors background CLI tasks"""

    def __init__(self, base_dir: str="bg_tasks"):
        #folder to store output logs + metadata
        self.base_dir=Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)

        #task counter + memory for tracking them

        self.tasks=[]
        self.task_counter=0

        #file to remember tasks between runs
        self.metadata_file=self.base_dir / "tasks_metadata.json"
        self._load_tasks()

    
    # ---------------------- File Persistence ----------------------

    def _load_tasks(self):
        """Load saved task info if it exists"""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file,"r") as f:
                    data=json.load(f)
                    self.tasks=data.get("tasks",[])
                    self.task_counter=data.get("counter",0)
            
            except Exception:
                #corrupted file? start fresh
                self.tasks, self.task_counter=[],0


    def _save_tasks(self):
        """Save task list + counter to disk"""
        try:
            with open(self.metadata_file,"w",encoding="utf-8") as f:
                json.dump({"tasks":self.tasks, "counter":self.task_counter},f,indent=2)
        except Exception:
            pass # don't crash if saving fails

    
    # ---------------------- Task Launching ----------------------
    def run_background_task(self, command:str,args:List[str],max_runtime: int=300)->Tuple[str,Path]:
        """
        Launch a tool like gobuster/nikto in the background.
        It logs all output to a file and tracks runtime
        """

        self.task_counter+=1
        task_id=f"{command}_{self.task_counter}_{int(time.time())}"

        #file where tool output will be saved
        output_file=self.base_dir / f"{task_id}.txt"

        #cmd to execute -> e.g., ["gobuster","dir","-u","https://site","-w","/wordlist.txt"]
        cmd=[command]+args

        #start the command in background using subprocess
        with open(output_file,"w",encoding="utf-8") as f:
            proc=subprocess.Popen(
                cmd,
                stdout=f,                   #write tool output to file
                stderr=subprocess.STDOUT,   #merge stdout+stderr
                text=True,                  #write as text, not bytes
                start_new_session=True      #run in new process group
            )

        #save metadata about this task
        task={
            "id":task_id,
            "command": command,
            "args":args,
            "pid":proc.pid,      #process ID for tracking
            "output_file":str(output_file),
            "start_time":time.time(),
            "max_runtime":max_runtime,
            "completed":False
        }

        self.tasks.append(task)
        self._save_tasks()

        #return ID and file path for reference
        return task_id, output_file
    
    
    # ---------------------- Task Management ----------------------
    def terminate_expired_or_idle_tasks(self, idle_time:int=5):
        """Kill processes that exceed allowed runtime or idle_time"""
        for task in self.tasks:
            if task["completed"]:
                continue

            runtime=time.time()-task["start_time"]

            #runtime exceeded
            if runtime>task.get("max_runtime",300):
                self._terminate_task(task,reason="max_runtime")
                continue

            #output file idle
            output_path=Path(task["output_file"])
            if self._is_file_idle(output_path,idle_time=idle_time):
                self._terminate_task(task,reason=f"idle>{idle_time}s")
                continue

        self._save_tasks()

    
    def _terminate_task(self,task:Dict,reason: str="terminated"):
        """terminates a process by pid, 
        first tries process-group(unix) then fallbacks to single pid kill(windows),
        marks task completed and records reason
         """
        pid=task.get("pid")
        if not pid:
            task["completed"]=True
            task["terminated"]=True
            task["terminated_reason"]="no_pid"
            return
        try:
            #kill process-group(unix)
            os.killpg(pid,signal.SIGTERM)
        except Exception:
            try:
                #fallback kill single process(windows)
                os.kill(pid,signal.SIGTERM)
            except Exception:
                pass
        
        task["completed"]=True
        task["terminated"]=True
        task["terminated_reason"]=reason
        task["completion_time"]=time.time()


    # ---------------------- Output Checking ----------------------
    def _is_file_idle(self,file_path:Path,idle_time:int=5)->bool:
        """
        check if file hasn't been modified for 'idle_time' seconds.
        Means the process has likely stopped working
        """
        if not file_path.exists():
            return False
        try:
            if file_path.stat().st_size==0:
                return False
            last_mod=file_path.stat().st_mtime
            return  (time.time()-last_mod) >=idle_time
        except Exception:
            return False
        

    def check_completed_tasks(self,idle_time:int=5)->List[Dict]:
        """Returns list of tasks that appears finished"""
        completed=[]
        self.terminate_expired_or_idle_tasks(idle_time=idle_time)

        for task in self.tasks:
            if task["completed"]:
                continue

            output_path=Path(task["output_file"])
            if self._is_file_idle(output_path,idle_time=idle_time):
                task["completed"]=True
                task["terminated_reason"]="completed"
                task["completed_time"]=time.time()
                completed.append(task)

        if completed:
            self._save_tasks()

        return completed
    

    async def wait_for_task_completion(self,
                                 task_id:str,
                                 timeout:int,
                                 poll_interval:float=2.0,
                                 idle_time:int=5)->Optional[Dict]:
        """
        Wait for a specific task to appear completed or reach idle state or timeout.
        - task_id: ID returned by run_background_task
        - timeout: max seconds to wait
        - poll_interval: how often to check (seconds)
        - idle_time: file idle threshold to treat as completion
        Returns task dict (with 'output' if available) or None if timed out.
        """
        deadline=time.time()+timeout
        while time.time()<deadline:
            #check completed tasks and return if our task finished
            completed=self.check_completed_tasks(idle_time=idle_time)  
            #calls terminate_expired_or_idle_tasks internally for enforce termination condition(runtime or idle)

            for t in completed:
                if t["id"]==task_id:
                    return t
            
            await asyncio.sleep(poll_interval)
        return None


    # ---------------------- Quick Lookups ----------------------
    def get_task_output(self,task_id:str)->Optional[str]:
        """Fetch output text for a specific task by ID."""
        for task in self.tasks:
            if task["id"]==task_id:
                try:
                    with open(task["output_file"],"r",errors="ignore",encoding="utf-8") as f:
                        return f.read()
                except Exception:
                    return None
                
        return None
    
    def get_status(self)->Dict:
        """Returns overview of pending+copleted tasks."""
        pending=[t for t in self.tasks if not t["completed"]]
        done=[t for t in self.tasks if t["completed"]]

        return {
            "total":len(self.tasks),
            "pending":len(pending),
            "completed":len(done),
            "pending_tasks":[
                {
                "id":t["id"],
                "cmd":" ".join([t["command"]]+t["args"]),
                "runtime":int(time.time()-t["start_time"])
            }
            for t in pending
            ],
        }
    
# --------- Global helpers (easy imports for other modules) ---------

bg_manager=BackgroundTaskManager()

def launch_background_task(cmd:str, args:List[str],max_runtime: int=300):
    return bg_manager.run_background_task(cmd,args,max_runtime)

def check_for_completed_tasks():
    return bg_manager.check_completed_tasks()

def get_background_task_status():
    return bg_manager.get_status()

def get_task_output(task_id: str):
    return bg_manager.get_task_output(task_id)

async def wait_for_task(task_id:int,timeout:int,idle_time:int=5,poll_interval:int=2):
    return await bg_manager.wait_for_task_completion(task_id,timeout=timeout,idle_time=idle_time,poll_interval=poll_interval)