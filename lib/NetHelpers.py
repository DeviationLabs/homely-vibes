#!/usr/bin/env python3
import contextlib
import logging
from paramiko import SSHClient
from typing import Generator
import requests
import subprocess
import sys


# ping output, 1 line per row. Suppress bash retval
def ping_output(node, count=1, desired_up=True) -> bool:
    node_state = False
    cmd = "ping -c%d %s" % (count, node)
    try:
        output = subprocess.check_output(cmd.split(), timeout=5).decode("utf-8").splitlines()
        if not output:
            raise AssertionError(f"No data returned for {cmd=}. Needs debug")
        for line in output:
            if "0 received" in line:
                node_state = False
            elif "received" in line:
                node_state = True
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        AssertionError,
    ) as e:
        logging.debug(f"Ping failed. Got {e.__repr__()}")
        pass
    logging.debug("node %s: got %s" % (node, node_state))
    return node_state if desired_up else not node_state


# run a command in ssh and return string output
def ssh_cmd(node, user, passwd, winCmd) -> str:
    sshOpts = "-o ConnectTimeout=10"
    cmd = "sshpass -p %s ssh %s %s@%s %s 2> /dev/null" % (
        passwd,
        sshOpts,
        user,
        node,
        winCmd,
    )
    try:
        output = subprocess.check_output(cmd.split(), timeout=10).decode("utf-8")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        output = f"{e}"
    return output


# Create a paramiko SSH Client
def ssh_connect(node_ip, user, passwd) -> SSHClient:
    client = SSHClient()
    client.load_system_host_keys()
    client.connect(node_ip, username=user, password=passwd, timeout=10)
    # kill stale sshd processes if any. looks like this
    # will not kill current logged in process, but
    # double check
    ssh_cmd_v2(client, "sudo pkill sshd")
    try:
        ssh_cmd_v2(client, "ls")
    except Exception:
        print("Did I just shoot myself in the foot?")
        client.connect(node_ip, username=user, password=passwd, timeout=10)
    return client


# Run a command on client and return string output
def ssh_cmd_v2(client, remote_cmd) -> str:
    if client is None:
        raise AssertionError("No Client\n")
    stdin, stdout, stderr = client.exec_command(remote_cmd, timeout=5)
    return "".join(stdout.readlines()) + "".join(stderr.readlines())


# Run an http request and return string output
def http_req(cmd) -> str:
    resp_text = "\n"
    resp = requests.get(cmd)
    resp_text = " ".join(resp.text.split("\n"))
    return resp_text


# Suppress stdout.
@contextlib.contextmanager
def no_stdout() -> Generator[None, None, None]:
    class DummyFile(object):
        def write(self, x):
            pass

    save_stdout = sys.stdout
    sys.stdout = DummyFile()
    yield
    sys.stdout = save_stdout


# Send the stdout to a random file.
def redirect_to_file(text):
    original = sys.stdout
    sys.stdout = open("/dev/null", "w")
    print("This is your redirected text:")
    print(text)
    sys.stdout = original
