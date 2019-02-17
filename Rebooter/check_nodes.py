#!/usr/bin/env python3.6
import argparse
import logging
import re
import sys
import time
import Mailer
import Constants
import NetHelpers

system_unhealthy = False
state = dict()
message = ""

#### Helper Functions ####

def reboot_foscam(node):
  cmd = "http://%s:88//cgi-bin/CGIProxy.fcgi?cmd=rebootSystem&usr=%s&pwd=%s" \
        % (node, Constants.FOSCAM_USERNAME, Constants.FOSCAM_PASSWORD)
  return NetHelpers.http_req(cmd)


def reboot_windows(node):
  # Ping to keep child proc alive for long enough
  winCmd = "shutdown /r /f ; ping localhost -n 3 > nul"
  return NetHelpers.ssh_cmd(node, Constants.WINDOWS_USERNAME, Constants.WINDOWS_PASSWORD, winCmd)


def check_deep_state(node):
  winCmd = "net statistics workstation"
  output = NetHelpers.ssh_cmd(node, Constants.WINDOWS_USERNAME, Constants.WINDOWS_PASSWORD, winCmd)
  if ("successful" in output):
    foundStr = re.search("Statistics since (.*)", output).group(1)
    output = "Up since %s" % foundStr
  return output


def log_message(msg):
  global message
  logging.info(msg)
  message += msg + "\n"


def check_state(desired_up, attempts):
  global state
  global system_unhealthy
  for nodeName, nodeIP in nodes.items():
    state[nodeName] = False
  for attempt in range(attempts):
    if all(state.values()):
      return
    time.sleep(1)
    for nodeName, nodeIP in nodes.items():
      # if state is false, then ping again to check if state is now true
      if not state[nodeName]:
        state[nodeName] = NetHelpers.ping_output(node=nodeIP, desired_up=desired_up)
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
  for nodeName, nodeIP in nodes.items():
    if state[nodeName]:
      log_message("%s: %s healthy." % (args.mode, nodeName))
      if args.mode == 'windows':
        # If windows and alive, do a deep check
        log_message(check_deep_state(nodeIP))
    else:
      log_message("%s: %s unhealthy." % (args.mode, nodeName))

  if args.reboot:
    log_message("Rebooting now...")
    for nodeName, nodeIP in nodes.items():
      if args.mode == 'foscam':
        logging.debug(reboot_foscam(nodeIP))
      else:
        logging.debug(reboot_windows(nodeIP))

    check_state(desired_up=False, attempts=180)
    for nodeName, nodeIP in nodes.items():
      if state[nodeName]:
        log_message("Confirmed node is down: %s" % nodeName)
      else:
        log_message("Oops! Failed to reboot: %s" % nodeName)

    log_message("Sleep until nodes restart...")
    check_state(desired_up=True, attempts=300)
    for nodeName, nodeIP in nodes.items():
      if state[nodeName]:
        log_message("%s: %s back online." % (args.mode, nodeName))
        if args.mode == 'windows':
          # If windows and alive, do a deep check
          time.sleep(60) # generously wait for processes to stabilize
          log_message(check_deep_state(nodeIP))
    if system_unhealthy:
      log_message("Failed to restart nodes...")
      logging.error('Hmm... overall badness')
    else:
      logging.info('All is well')

  Mailer.sendmail(topic="[NodeCheck-%s]" %args.mode, alert=system_unhealthy, \
                  message=message, always_email=args.always_email)
  print("Done!")
