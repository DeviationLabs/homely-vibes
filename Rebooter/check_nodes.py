#!/usr/bin/env python3.6
import argparse
import logging
import os
import requests
import subprocess
import sys
import time
import Mailer
import Constants

system_unhealthy = False
state = dict()
message = ""

#### Helper Functions ####

# ping output, 1 line per row. Suppress bash retval
def ping_output(node, count=1, desired_up=True):
  node_state = None
  cmd = "ping -c%d %s" % (count, node)
  try:
    output = subprocess.check_output(cmd.split())
  except subprocess.CalledProcessError as e:
    output = e.output
  for line in output.decode('utf-8').splitlines():
    if '0 received' in line:
       node_state = False
    elif 'received' in line:
       node_state = True
  logging.debug("node %s: got %s" % (node, node_state))
  return node_state if desired_up else not node_state


def reboot_foscam(node):
  cmd = "http://%s:88//cgi-bin/CGIProxy.fcgi?cmd=rebootSystem&usr=%s&pwd=%s" \
        % (node, Constants.FOSCAM_USERNAME, Constants.FOSCAM_PASSWORD)
  resp_text = '\n'
  try:
    resp = requests.get(cmd)
    resp_text = ' '.join(resp.text.split('\n'))
  except (OSError, Exception) as e:
    resp_text = "Something failed in reboot request on node: %s" % node
  return(resp_text)


def reboot_windows(node):
  winCmd = "shutdown /r /f ; ping localhost -n 3 ; net statistics workstation"
  sshOpts = '-o ConnectTimeout=10'
  cmd = "sshpass -p %s ssh %s %s@%s %s 2> /dev/null" \
        % (Constants.WINDOWS_PASSWORD, sshOpts, Constants.WINDOWS_USERNAME, node, winCmd)
  try:
    output = subprocess.check_output(cmd.split())
  except subprocess.CalledProcessError as e:
    output = e.output
  return output.decode('utf-8')


def log_message(msg):
  global message
  logging.info(msg)
  message += msg + "\n"


def check_state(desired_up, attempts):
  global state
  for node in nodes:
    state[node] = False
  for attempt in range(attempts):
    if all(state.values()):
      return
    time.sleep(1)
    for node in nodes:
      # if state is false, then ping again to check if state is now true
      if not state[node]:
        state[node] = ping_output(node=node, desired_up=desired_up)
  if not all(state.values()):
    system_unhealthy = True


#### Main Routine ####
if __name__ == "__main__":
  parser = argparse.ArgumentParser(description = "Reboot Utility")
  parser.add_argument('--mode',
                      help    ='Foscams or Windows(i.e.:Alpha)',
                      choices =['foscam','windows'],
                      default ='foscam')
  parser.add_argument('--reboot',
                      help    ='Reboot or check only',
                      action  ='store_true',
                      default =False)
  parser.add_argument('--always_email',
                      help    ='Send email report',
                      action  ='store_true',
                      default =False)
  parser.add_argument('--out_dir',
                      help    ='Folder for storing output files',
                      default ='%s/Junk/' % Constants.HOME)
  args = parser.parse_args()

  logfile = '%s/check_nodes.txt' % args.out_dir
  log_format = '%(levelname)s:%(module)s.%(lineno)d:%(asctime)s: %(message)s'
  logging.basicConfig(filename=logfile, format=log_format, level=logging.DEBUG)
  logging.info('============')
  logging.info('Invoked command: %s' % ' '.join(sys.argv))

  nodes = Constants.FOSCAM_NODES if args.mode == 'foscam' \
          else Constants.WINDOWS_NODES

  check_state(desired_up=True, attempts=1)
  for node in nodes:
    if state[node]:
      log_message("Node %s healthy." % node)
    else:
      log_message("Node %s unhealthy." % node)

  if args.reboot:
    log_message("Rebooting now...")
    for node in nodes:
      if args.mode == 'foscam':
        log_message(reboot_foscam(node))
      else:
        log_message(reboot_windows(node))

    check_state(desired_up=False, attempts=180)
    for node in nodes:
      if state[node]:
        log_message("Confirmed node is down: %s" % node)
      else:
        log_message("Oops! Failed to reboot: %s" % node)

    log_message("Sleep until nodes restart...")
    check_state(desired_up=True, attempts=300)
    for node in nodes:
      if state[node]:
        log_message("%s[%s] back online." % (args.mode, node))

  Mailer.sendmail(topic="[NodeCheck-%s]" %args.mode, alert=system_unhealthy, \
                  message=message, always_email=args.always_email)
  if system_unhealthy:
    logging.error('Hmm... overall badness')
  else:
    logging.info('All is well')
  print("Done!")
