"""
background_tasks.py - handles background execution of long-running tools
like gobuster, nmap(-p-), nikto, etc.
each task runs separately, logs to a file, and can be checked later
"""

import os
import time
import subprocess
import signal
import json
import fcntl
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import asyncio
import threading


class BackgroundTaskManager:
    """Runs and monitors background CLI tasks"""

    def __init__(self, base_dir: str = "bg_tasks"):
        # folder to store output logs + metadata
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)

        # task counter + memory for tracking them
        self.tasks = []
        self.task_counter = 0

        # file to remember tasks between runs
        self.metadata_file = self.base_dir / "tasks_metadata.json"
        self.lockfile = self.base_dir / "tasks.lock"
        
        # Thread lock for in-memory operations
        self._lock = threading.RLock()
        
        self._load_tasks()

    # ---------------------- File Locking ----------------------

    def _acquire_file_lock(self, timeout: int = 10):
        """Acquire exclusive file lock with timeout"""
        lock_fd = os.open(self.lockfile, os.O_CREAT | os.O_RDWR)
        start_time = time.time()
        
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return lock_fd
            except BlockingIOError:
                if time.time() - start_time > timeout:
                    os.close(lock_fd)
                    raise TimeoutError("Could not acquire file lock")
                time.sleep(0.1)

    def _release_file_lock(self, lock_fd: int):
        """Release file lock"""
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        except Exception:
            pass

    # ---------------------- File Persistence ----------------------

    def _load_tasks(self):
        """Load saved task info if it exists"""
        with self._lock:
            if self.metadata_file.exists():
                lock_fd = None
                try:
                    lock_fd = self._acquire_file_lock()
                    with open(self.metadata_file, "r") as f:
                        data = json.load(f)
                        self.tasks = data.get("tasks", [])
                        self.task_counter = data.get("counter", 0)
                except TimeoutError:
                    print("Warning: Could not acquire lock for loading tasks")
                    self.tasks, self.task_counter = [], 0
                except Exception as e:
                    # corrupted file? start fresh
                    print(f"Warning: Could not load task metadata: {e}")
                    self.tasks, self.task_counter = [], 0
                finally:
                    if lock_fd is not None:
                        self._release_file_lock(lock_fd)

    def _save_tasks(self):
        """Save task list + counter to disk with file locking"""
        with self._lock:
            lock_fd = None
            try:
                lock_fd = self._acquire_file_lock()
                
                # Write to temporary file first (atomic write)
                temp_file = self.metadata_file.with_suffix('.json.tmp')
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(
                        {"tasks": self.tasks, "counter": self.task_counter}, 
                        f, 
                        indent=2
                    )
                    f.flush()
                    os.fsync(f.fileno())  # ensure data is written to disk
                
                # Atomic rename
                temp_file.replace(self.metadata_file)
                
            except TimeoutError:
                print("Warning: Could not acquire lock for saving tasks")
            except Exception as e:
                print(f"Warning: Could not save task metadata: {e}")
            finally:
                if lock_fd is not None:
                    self._release_file_lock(lock_fd)

    # ---------------------- Task Launching ----------------------
    def run_background_task(
        self, command: str, args: List[str], max_runtime: int = 300
    ) -> Tuple[str, Path]:
        """
        Launch a tool like gobuster/nikto in the background.
        It logs all output to a file and tracks runtime
        Thread-safe for concurrent launches.
        """
        with self._lock:
            self.task_counter += 1
            task_id = f"{command}_{self.task_counter}_{int(time.time())}"

            # file where tool output will be saved
            output_file = self.base_dir / f"{task_id}.txt"

            # cmd to execute -> e.g., ["gobuster","dir","-u","https://site","-w","/wordlist.txt"]
            cmd = [command] + args

            # start the command in background using subprocess
            try:
                with open(output_file, "w", encoding="utf-8") as f:
                    proc = subprocess.Popen(
                        cmd,
                        stdout=f,
                        stderr=subprocess.STDOUT,
                        text=True,
                        start_new_session=True,
                    )
            except Exception as e:
                raise RuntimeError(f"Failed to start background task: {e}")

            # save metadata about this task
            task = {
                "id": task_id,
                "command": command,
                "args": args,
                "pid": proc.pid,  # process ID for tracking
                "output_file": str(output_file),
                "start_time": time.time(),
                "max_runtime": max_runtime,
                "completed": False,
            }

            self.tasks.append(task)
            self._save_tasks()

            # return ID and file path for reference
            return task_id, output_file

    # ---------------------- Task Management ----------------------
    def _is_process_alive(self, pid: int) -> bool:
        """Check if process is still running"""
        if not pid:
            return False
        try:
            # signal 0 doesn't kill, just checks if process exists
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            # Process doesn't exist
            return False
        except PermissionError:
            # Process exists but we don't have permission (still alive)
            return True
        except Exception:
            return False

    def terminate_expired(self):
        """Kill processes that exceed allowed runtime"""
        with self._lock:
            modified = False
            for task in self.tasks:
                if task.get("completed"):
                    continue

                runtime = time.time() - task["start_time"]

                # runtime exceeded
                if runtime > task.get("max_runtime", 300):
                    self._terminate_task(task, reason="max_runtime")
                    modified = True

            if modified:
                self._save_tasks()

    def _terminate_task(self, task: Dict, reason: str = "terminated"):
        """
        Terminates a process by pid,
        kills the entire process group,
        marks task completed and records reason
        Note: Should be called within a lock
        """
        pid = task.get("pid")
        if not pid:
            task["completed"] = True
            task["terminated"] = True
            task["terminated_reason"] = "no_pid"
            return

        try:
            # Get process group ID and kill entire group
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGTERM)
            
            # Give it a moment to terminate gracefully
            time.sleep(0.5)
            
            # Force kill if still alive
            if self._is_process_alive(pid):
                os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            # Process already dead
            pass
        except Exception as e:
            # Fallback: try to kill just the main process
            try:
                os.kill(pid, signal.SIGTERM)
                time.sleep(0.5)
                if self._is_process_alive(pid):
                    os.kill(pid, signal.SIGKILL)
            except Exception:
                print(f"Warning: Could not terminate process {pid}: {e}")

        task["completed"] = True
        task["terminated"] = True
        task["terminated_reason"] = reason
        task["completion_time"] = time.time()

    # ---------------------- Output Checking ----------------------

    def check_completed_tasks(self) -> List[Dict]:
        """Returns list of tasks that have finished (process no longer running)"""
        with self._lock:
            completed = []
            self.terminate_expired()

            for task in self.tasks:
                if task.get("completed"):
                    continue

                # Check if process is still alive
                pid = task.get("pid")
                if pid and not self._is_process_alive(pid):
                    task["completed"] = True
                    task["terminated_reason"] = "completed"
                    task["completion_time"] = time.time()
                    completed.append(task.copy())  # Return copy to avoid external modifications

            if completed:
                self._save_tasks()

            return completed

    async def wait_for_task_completion(
        self,
        task_id: str,
        timeout: int,
        poll_interval: float = 2.0,
    ) -> Optional[Dict]:
        """
        Wait for a specific task to complete (process exits) or timeout.
        - task_id: ID returned by run_background_task
        - timeout: max seconds to wait
        - poll_interval: how often to check (seconds)
        Returns task dict or None if timed out.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            # check completed tasks and return if our task finished
            completed = self.check_completed_tasks()

            for t in completed:
                if t["id"] == task_id:
                    # Add output to task dict
                    output = self.get_task_output(task_id)
                    if output:
                        t["output"] = output
                    return t

            await asyncio.sleep(poll_interval)
        
        # Timeout reached - return None
        return None

    # ---------------------- Quick Lookups ----------------------
    def get_task_output(self, task_id: str) -> Optional[str]:
        """Fetch output text for a specific task by ID."""
        with self._lock:
            for task in self.tasks:
                if task["id"] == task_id:
                    output_file = task.get("output_file")
                    if not output_file:
                        return None
                    try:
                        with open(output_file, "r", errors="ignore", encoding="utf-8") as f:
                            return f.read()
                    except Exception:
                        return None

            return None

    def get_task_by_id(self, task_id: str) -> Optional[Dict]:
        """Get task metadata by ID"""
        with self._lock:
            for task in self.tasks:
                if task["id"] == task_id:
                    return task.copy()  # Return copy to prevent external modifications
            return None

    def get_status(self) -> Dict:
        """Returns overview of pending+completed tasks."""
        with self._lock:
            pending = [t for t in self.tasks if not t.get("completed")]
            done = [t for t in self.tasks if t.get("completed")]

            return {
                "total": len(self.tasks),
                "pending": len(pending),
                "completed": len(done),
                "pending_tasks": [
                    {
                        "id": t["id"],
                        "cmd": " ".join([t["command"]] + t["args"]),
                        "runtime": int(time.time() - t["start_time"]),
                    }
                    for t in pending
                ],
            }

    def cleanup_old_tasks(self, max_age_days: int = 7):
        """Remove tasks and their output files older than max_age_days"""
        with self._lock:
            cutoff_time = time.time() - (max_age_days * 24 * 3600)
            tasks_to_keep = []
            
            for task in self.tasks:
                if task["start_time"] < cutoff_time:
                    # Delete output file
                    try:
                        output_file = Path(task["output_file"])
                        if output_file.exists():
                            output_file.unlink()
                    except Exception as e:
                        print(f"Warning: Could not delete old task file: {e}")
                else:
                    tasks_to_keep.append(task)
            
            self.tasks = tasks_to_keep
            self._save_tasks()


# --------- Global helpers (easy imports for other modules) ---------

bg_manager = BackgroundTaskManager()


def launch_background_task(cmd: str, args: List[str], max_runtime: int = 500):
    return bg_manager.run_background_task(cmd, args, max_runtime)


def check_for_completed_tasks():
    return bg_manager.check_completed_tasks()


def get_background_task_status():
    return bg_manager.get_status()


def get_task_output(task_id: str):
    return bg_manager.get_task_output(task_id)


def get_task_by_id(task_id: str):
    return bg_manager.get_task_by_id(task_id)


async def wait_for_task(task_id: str, timeout: int, poll_interval: float = 2.0):
    return await bg_manager.wait_for_task_completion(
        task_id, timeout=timeout, poll_interval=poll_interval
    )


"""
Helper functions for running security tools in background with minimal boilerplate, this is a waiting fuction do we will not be using it
"""

from prototype.mcp_stuff.background_tasks import launch_background_task, wait_for_task
from pathlib import Path
from typing import Optional, List, Dict, Tuple
import asyncio


async def run_tool_background(
    tool_name: str,
    args: List[str],
    max_runtime: int = 300,
    poll_interval: float = 2.0,
    verbose: bool = True
) -> Dict[str, any]:
    """
    Generic helper to run any CLI tool in background and get results.
    
    Args:
        tool_name: Command to execute (e.g., 'nmap', 'gobuster', 'nikto')
        args: List of arguments for the tool
        max_runtime: Maximum seconds to let tool run
        poll_interval: How often to check if tool completed (seconds)
        verbose: Print status messages
    
    Returns:
        Dict with keys:
            - success: bool
            - output: str (tool output)
            - task_id: str
            - completed: bool (True if finished naturally, False if timeout)
            - error: str (if any error occurred)
    """
    
    # Launch background task
    try:
        task_id, output_file = launch_background_task(tool_name, args, max_runtime=max_runtime)
    except Exception as e:
        return {
            "success": False,
            "output": "",
            "task_id": None,
            "completed": False,
            "error": f"Failed to launch {tool_name}: {str(e)}"
        }
    
    if verbose:
        print(f"[+] {tool_name} started (Task ID: {task_id})")
        print(f"    Command: {tool_name} {' '.join(args)}")
        print(f"    Output file: {output_file}")
        print(f"    Max runtime: {max_runtime}s")
    
    # Wait for completion
    res = await wait_for_task(task_id, timeout=max_runtime, poll_interval=poll_interval)
    
    # Handle timeout case
    if res is None:
        if verbose:
            print(f"[!] {tool_name} timed out after {max_runtime}s")
        
        # Try to read partial output
        p = Path(output_file)
        if p.exists():
            try:
                output = p.read_text(errors="ignore")
                return {
                    "success": True,
                    "output": output,
                    "task_id": task_id,
                    "completed": False,
                    "error": f"Timeout after {max_runtime}s (partial output returned)"
                }
            except Exception as e:
                return {
                    "success": False,
                    "output": "",
                    "task_id": task_id,
                    "completed": False,
                    "error": f"Timeout and could not read output: {str(e)}"
                }
        
        return {
            "success": False,
            "output": "",
            "task_id": task_id,
            "completed": False,
            "error": f"Timeout after {max_runtime}s (no output available)"
        }
    
    # Task completed successfully
    if verbose:
        print(f"[✓] {tool_name} completed (Task ID: {task_id})")
    
    # Get output (either from result dict or file)
    output = res.get("output", "")
    if not output:
        output_path = Path(res.get("output_file", output_file))
        if output_path.exists():
            try:
                output = output_path.read_text(errors="ignore")
            except Exception:
                pass
    
    return {
        "success": True,
        "output": output,
        "task_id": task_id,
        "completed": True,
        "error": None
    }


# ============================================================================
# Tool-specific wrappers (minimal code, just validates inputs)
# ============================================================================

async def run_feroxbuster(
    url: str,
    wordlist: str = "/usr/share/wordlists/dirb/common.txt",
    threads: int = 50,
    depth: int = 4,
    extensions: Optional[List[str]] = None,
    runtime: int = 300,
    poll_interval: float = 2.0,
    verbose: bool = True
) -> Dict[str, any]:
    """Run feroxbuster directory bruteforcer"""
    
    if not Path(wordlist).exists():
        return {
            "success": False,
            "output": "",
            "task_id": None,
            "completed": False,
            "error": f"Wordlist not found: {wordlist}"
        }
    
    args = ["-u", url, "-w", wordlist, "-t", str(threads), "-d", str(depth)]
    
    if extensions:
        args.extend(["-x", ",".join(extensions)])
    
    return await run_tool_background("feroxbuster", args, runtime, poll_interval, verbose)


async def run_gobuster(
    url: str,
    wordlist: str = "/usr/share/wordlists/dirb/common.txt",
    threads: int = 50,
    extensions: Optional[List[str]] = None,
    runtime: int = 300,
    poll_interval: float = 2.0,
    verbose: bool = True
) -> Dict[str, any]:
    """Run gobuster directory bruteforcer"""
    
    if not Path(wordlist).exists():
        return {
            "success": False,
            "output": "",
            "task_id": None,
            "completed": False,
            "error": f"Wordlist not found: {wordlist}"
        }
    
    args = ["dir", "-u", url, "-w", wordlist, "-t", str(threads)]
    
    if extensions:
        args.extend(["-x", ",".join(extensions)])
    
    return await run_tool_background("gobuster", args, runtime, poll_interval, verbose)


async def run_nmap(
    target: str,
    ports: str = "-p-",
    scan_type: str = "-sV",
    additional_args: Optional[List[str]] = None,
    runtime: int = 600,
    poll_interval: float = 5.0,
    verbose: bool = True
) -> Dict[str, any]:
    """Run nmap port scanner"""
    
    args = [scan_type, ports, target]
    
    if additional_args:
        args.extend(additional_args)
    
    return await run_tool_background("nmap", args, runtime, poll_interval, verbose)


async def run_nikto(
    target: str,
    port: int = 80,
    ssl: bool = False,
    runtime: int = 600,
    poll_interval: float = 5.0,
    verbose: bool = True
) -> Dict[str, any]:
    """Run nikto web server scanner"""
    
    args = ["-h", target, "-p", str(port)]
    
    if ssl:
        args.append("-ssl")
    
    return await run_tool_background("nikto", args, runtime, poll_interval, verbose)


async def run_wpscan(
    url: str,
    enumerate: str = "vp,vt,u",
    runtime: int = 600,
    poll_interval: float = 5.0,
    verbose: bool = True
) -> Dict[str, any]:
    """Run wpscan WordPress scanner"""
    
    args = ["--url", url, "--enumerate", enumerate]
    
    return await run_tool_background("wpscan", args, runtime, poll_interval, verbose)


async def run_ffuf(
    url: str,
    wordlist: str = "/usr/share/wordlists/dirb/common.txt",
    keyword: str = "FUZZ",
    match_codes: str = "200,204,301,302,307,401,403,405",
    threads: int = 40,
    runtime: int = 300,
    poll_interval: float = 2.0,
    verbose: bool = True
) -> Dict[str, any]:
    """Run ffuf fuzzer"""
    
    if not Path(wordlist).exists():
        return {
            "success": False,
            "output": "",
            "task_id": None,
            "completed": False,
            "error": f"Wordlist not found: {wordlist}"
        }
    
    fuzz_url=url.strip()+keyword
    
    args = [
        "-u", fuzz_url,
        "-w", wordlist,
        "-mc", match_codes,
        "-t", str(threads)
    ]
    
    return await run_tool_background("ffuf", args, runtime, poll_interval, verbose)


# ============================================================================
# Example usage
# ============================================================================

async def main():
    """Example: Run multiple tools concurrently"""
    
    target = "http://example.com"
    
    # Run multiple tools in parallel
    results = await asyncio.gather(
        run_feroxbuster(target, runtime=120),
        run_nikto(target, runtime=300),
        run_nmap("example.com", runtime=600),
    )
    
    print("\n" + "="*60)
    print("RESULTS SUMMARY")
    print("="*60)
    
    for i, result in enumerate(results, 1):
        print(f"\nTool {i}:")
        print(f"  Success: {result['success']}")
        print(f"  Completed: {result['completed']}")
        print(f"  Task ID: {result['task_id']}")
        if result['error']:
            print(f"  Error: {result['error']}")
        print(f"  Output length: {len(result['output'])} chars")


# if __name__ == "__main__":
#     asyncio.run(main())