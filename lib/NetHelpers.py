#!/usr/bin/env python3.6
import contextlib
import logging
from paramiko import SSHClient
import requests
import subprocess
import sys


# ping output, 1 line per row. Suppress bash retval
def ping_output(node, count=1, desired_up=True):
  node_state = None
  cmd = "ping -c%d %s" % (count, node)
  try:
    output = subprocess.check_output(cmd.split(), timeout=5)
  except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
    output = e.output
  for line in output.decode('utf-8').splitlines():
    if '0 received' in line:
       node_state = False
    elif 'received' in line:
       node_state = True
  logging.debug("node %s: got %s" % (node, node_state))
  return node_state if desired_up else not node_state

# run a command in ssh and return string output
def ssh_cmd(node, user, passwd, winCmd):
  sshOpts = '-o ConnectTimeout=10'
  cmd = "sshpass -p %s ssh %s %s@%s %s 2> /dev/null" \
        % (passwd, sshOpts, user, node, winCmd)
  try:
    output = subprocess.check_output(cmd.split(), timeout=10).decode('utf-8')
  except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
    output = f'{e}'
  return output


# run a command in ssh and return string output
def ssh_connect(node, user, passwd):
  client = SSHClient()
  client.load_system_host_keys()
  client.connect(node, username=user, password=passwd, timeout=10)
  return client


def ssh_cmd_v2(client, remote_cmd):
  stdin, stdout, stderr = client.exec_command(remote_cmd, timeout=5)
  errors = stderr.readlines()
  if len(errors) > 0:
    return ''.join(errors)
  else:
    return ''.join(stdout.readlines())


# Run an http request and return string output
def http_req(cmd):
  resp_text = '\n'
  resp = requests.get(cmd)
  resp_text = ' '.join(resp.text.split('\n'))
  return(resp_text)


# Suppress stdout.
@contextlib.contextmanager
def no_stdout():
  class DummyFile(object):
    def write(self, x): pass
  save_stdout = sys.stdout
  sys.stdout = DummyFile()
  yield
  sys.stdout = save_stdout


# Send the stdout to a random file.
def redirect_to_file(text):
  original = sys.stdout
  sys.stdout = open('/dev/null', 'w')
  print('This is your redirected text:')
  print(text)
  sys.stdout = original
