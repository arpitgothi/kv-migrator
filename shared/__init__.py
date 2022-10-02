import argparse
from enum import Enum
from termcolor import colored
import sys
import os
import re
from time import perf_counter
#import logging

class CloudProvider(Enum):
    AWS = "AWS"
    GCP = "GCP"

def time_table(start_time):
    end_time = perf_counter()
    total_time = int(end_time - start_time)
    print(f"\n    Script ran for {total_time} seconds.\n")
    
def script_exit(rc):
    if rc != 0:
        print(colored(f'''\n
    Script failed to complete. Review the stack's status.\n
            Please take necessary action regarding Downtime in Thruk and SFX.
            \n
        Text below red line is helpful for code owners' troubleshooting...
-----------------------------------------------------------------------------''', "red"))
        raise RuntimeError(rc)
    sys.exit(rc)
    
def print_header(text: str):
    print(colored(f" --- {text} ---", "cyan"))

def print_warning(text: str):
    print(colored(f" !!!! {text} !!!! ", "yellow"))

def print_info(text: str):
    print(colored(f" !!!! {text} !!!! ", "blue"))

def print_succ(text: str):
    print(colored(f" >>>> {text} <<<< ", "green"))

def print_error(text: str):
    print(colored(f" !*!*! !*!*! !*!*!\n {text} \n !*!*! !*!*! !*!*! ", "red"))
    script_exit(text)


def parse_args():# -> (str, str, str, bool, bool):
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--stack", help="Required : Stack name", required=True)
    parser.add_argument("-t", "--ticket", help="Required : TO Jira number", required=True)
    parser.add_argument("-e", "--env", help="Optional : CO2 environment - dev, stg, lve/prod. Default is lve/prod.",
                        default="prod")
    parser.add_argument("-n", "--name", help=f"Optional : List Name(s) of the SH in CO2 [-n sh1, sh2, etc.]. Default = \"all\" ", action='extend',
                        nargs='+', type=str)
    #parser.add_argument("--skip_dt", help="Optional : Skips setting Downtime in monitoring", action='store_true', default=False)
    parser.add_argument("--skip_dt", help=argparse.SUPPRESS, action='store_true', default=False)
    #parser.add_argument("--backout", help="Backout CO2 changes for KV migration", action='store_true', default=False)
    parser.add_argument("--backout", help=argparse.SUPPRESS, action='store_true', default=False)
    args = parser.parse_args()

    stack = args.stack.lower()
    ticket = args.ticket.upper()
    env = args.env.lower()
    search_nodes = []
    if args.name == None:
        search_nodes = ['all']
    elif 'all' in args.name:
        print("Detected 'all' in the names input, ignoring any other input for names")
        search_nodes = ['all']
    elif args.name != None: 
        for name in args.name:
            search_nodes.append(name.lower().strip(','))
    #else:
    #    search_nodes = ['all']

    for node in search_nodes:
        #['sh1', 'sh2', 'sh3', 'sh4', 'sh5', 'sh6', 'sh7', 'sh8', 'sh9', 'sh10', 'shc1', 'shc2', 'shc3', 'all']:
        if bool(re.search('^(all|sh(c[1-3]|[1-9]|1[0-5]))$', node)):
            continue
        else:
            print_error(f'SH "{node}" is not an acceptable SH Name. Please use one of sh1, sh2, ... sh15, or shc1')
    skip_dt = args.skip_dt
    backout = args.backout

    if env == "lve":
        env = "prod"
    elif env not in ["dev", "stg", "prod", "lve"]:
        raise ValueError(f"Environment {env} is not recognized.")

    return stack, ticket, env, skip_dt, search_nodes, backout

def script_pre_req_check(env):
    #check for cloudctl
    if not os.path.exists("/usr/local/bin/cloudctl"):
        print_error("cloudctl not installed?")

    #check for sfx-cli and tokens in env
    sfx_install_url = "https://cd.splunkdev.com/splunkcloud-sre/sre-go/sfx-cli"
    if not os.path.exists("/usr/local/bin/sfx-cli"):
        print_error(f"sfx-cli not installed. Please see: {sfx_install_url}")
    sfx_env = "sfx_token_us2"
    if env == "stg":
        sfx_env = "sfx_token_us1"
    if os.environ.get(sfx_env) == None:
        print_error(f"sfx-cli api tokens not found. Please see: {sfx_install_url}")
    
    #check for okta-aws-login
    if not os.path.exists("/usr/local/bin/okta-aws-login"):
        print_error()
        
    return sfx_env

def py_ver_check():
    if not sys.version_info >= (3,8):
        print_error("There is a reason to upgrade to python 3.8, and it is needed for this script")