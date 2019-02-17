#!/usr/bin/env python3.5
import contextlib
import logging
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
    output = subprocess.check_output(cmd.split(), timeout=10)
  except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
    output = e.output
  return output.decode('utf-8')


# Run an http request and return string output
def http_req(cmd):
  resp_text = '\n'
  try:
    resp = requests.get(cmd)
    resp_text = ' '.join(resp.text.split('\n'))
  except (OSError, Exception) as e:
    resp_text = "Something failed in reboot request on node: %s" % node
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
