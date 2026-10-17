"""Ask Codex itself for the registered tool catalog. No model turn or host input."""
import argparse
import json
import pathlib
import queue
import subprocess
import threading
import time

from validate_zvm_mcp import EXPECTED


def verify():
    process = subprocess.Popen(["codex", "app-server", "--stdio"], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    messages = queue.Queue()
    errors = []

    def read_stdout():
        for line in process.stdout:
            messages.put(json.loads(line))
        messages.put(None)

    def read_stderr():
        errors.extend(process.stderr.readlines())

    threads = [threading.Thread(target=read_stdout, daemon=True),
               threading.Thread(target=read_stderr, daemon=True)]
    for thread in threads:
        thread.start()

    def send(message):
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()

    def request(identifier, method, params):
        send({"id": identifier, "method": method, "params": params})
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            message = messages.get(timeout=max(0.01, deadline - time.monotonic()))
            if message is None:
                raise RuntimeError("Codex exited: " + "".join(errors))
            if message.get("id") == identifier:
                if "error" in message:
                    raise RuntimeError(json.dumps(message["error"]))
                return message["result"]
        raise TimeoutError("Codex discovery timed out")

    try:
        request(1, "initialize", {"clientInfo": {"name": "zvm-mcp-verifier", "version": "1.0"}})
        send({"method": "initialized", "params": {}})
        result = request(2, "mcpServerStatus/list", {"serverName": "ibm-zvm-cms", "detail": "toolsAndAuthOnly"})
        servers = [server for server in result["data"] if server["name"] == "ibm-zvm-cms"]
        assert len(servers) == 1, result
        names = {tool["name"] for tool in servers[0]["tools"].values()}
        assert names == EXPECTED, servers[0]
        return {"ok": True, "server": "ibm-zvm-cms", "discovered_by": "codex app-server",
                "tools": sorted(names), "tools_error": servers[0].get("toolsError")}
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        for thread in threads:
            thread.join(timeout=1)
        process.stdout.close()
        process.stderr.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    data = json.dumps(verify(), indent=2)
    if args.output:
        args.output.write_text(data + "\n")
    print(data)
