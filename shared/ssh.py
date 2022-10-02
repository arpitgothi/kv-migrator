from pprint import pprint
from sys import stdout
import time

from typing import Counter, List

from subprocess import Popen, PIPE, DEVNULL

from shared.aws import AWSStack, AWSInstance
from shared import print_header, print_warning, print_info, print_succ, print_error


# -> (int, str, str, str)
def run_remote_command(host: object, command: str, type: str = 'run', raise_on_error: bool = True, stdin: str = None) -> (int, str, str, str):
    """Runs a command on a server via SSH

    Parameters
    ----------
    host: AWSStack object
        Host (object) to connect to

    command: str
        Shell command to execute

    raise_on_error: bool
        Whether a RuntimeError should be raised when the command returns a non-zero exit code (optional, default True)

    stdin: str
        Input to pass to the command via stdin (optional)

    Raises
    ------
    RuntimeError
        If raise_on_error is True and the command returns a non-zero exit code

    Returns
    -------
    Tuple[int, str, str]
        Exit code, stdout, and stderr of remote command
    """

    if stdin is not None:
        stdin = stdin.encode("utf-8")
    team = 'splunk'
    if host.env not in ['lve', 'prod']:
        team = f"splunk-{host.env}"
    """if host.env != 'stg': #not in stg yet
        bastioncommand = f'--via {host.bastion}'"""
    bastioncommand = f'--via {host.bastion}'
    
    if 'nagios' in command:
        hostname = host.ca_host
    else:
        '''if host.env == 'stg':
            hostname = host.ssh_host
            #ssh=['ssh', '-F', 'ssh_config', hostname, command]
            ssh=['ssh', '-F', '/dev/null', hostname, '-oStrictHostKeyChecking=no', '-J', host.bastion, command]
            #hostname = host.ssh_host
            #ssh = ['ssh', '-vv', '-oStrictHostKeyChecking=no', '-oUserKnownHostsFile=/dev/null', f'-oProxyCommand="ssh -W %h:%p {host.bastion}"', hostname, command]
        else:
            hostname = host.ssh_host
            ssh = ['ssh', '-F', f'ssh_config_{host.env}', '-oStrictHostKeyChecking=no', '-oUserKnownHostsFile=/dev/null', hostname, command]
            #hostname = host.fqdn
            #ssh = ['ssh', '-v', '-oStrictHostKeyChecking=no','-F', 'ssh_config', hostname, command]
        '''
        hostname = host.ssh_host
        ssh = ['sft', 'ssh', hostname, "--team", team, "--command", command]
        #hostname = host.fqdn
        #ssh = ['ssh', '-v', '-oStrictHostKeyChecking=no','-F', 'ssh_config', hostname, command]
    if type == 'rc':
        p = Popen(ssh, stdout=PIPE, stderr=PIPE, stdin=PIPE).wait(timeout=30)
        if p != 0:
            raise ConnectionError(f'SSH connection to {host.ssh_host} failed!')
    elif type == 'background':
        return Popen(ssh, stderr=DEVNULL, stdout=DEVNULL, stdin=DEVNULL).wait(timeout=1200)
    elif type == 'run':
        p = Popen(ssh, stdout=PIPE, stderr=PIPE, stdin=PIPE)
        '''
        p = Popen(["sft", "ssh", hostname, "--command", command],
                stdout=PIPE, stderr=PIPE, stdin=PIPE)
        '''
        out, err = p.communicate(input=stdin)
        

        if raise_on_error and p.returncode != 0:
            print_error(f"Remote command exited with code: {err}")
            #raise RuntimeError(f"Remote command exited with code: {p.returncode}")
        
        return p.returncode, out.decode(), err.decode()

def ca_host_ssh(command: str) -> (int, str, str):
    ca_host = "cloud-ansible-us-east-1.splunkcloud.com"
    ssh = ['sft', 'ssh', ca_host, '--team=splunk', '--command', command]
    p = Popen(ssh, stdout=PIPE, stderr=PIPE, stdin=PIPE)
    out, err = p.communicate()
    return p.returncode, out.decode(), err.decode()
    
    
def batch_connectivity_check(instances: AWSStack):
    """Ensures that each host in the stack is reachable, handles prompts to accept SSH host keys

    Parameters
    ----------
    instances: AWSStack
        Stack to check connectivity for

    Raises
    ------
    ConnectionError
        If we fail to connect to an instance in the stack
    """
    
    print_warning("You may be prompted to accept SSH host keys for each server, please answer yes")
    for host in instances.all_instances:
        
        rc = Popen(["sft", "ssh", host.ssh_host, "--command", 'echo "Connected to `hostname`"']).wait()
        if rc != 0:
            raise ConnectionError(f"SSH connection to {host.ssh_host} failed!")


def background_remote_command(hostname: str, command: str) -> Popen:
    """Runs a remote command in the background, without printing its output or waiting for completion

    Parameters
    ----------
    hostname: str
        Host to connect to

    command: str
        Shell command to execute

    Returns
    -------
    Popen
        Reference to remote process
    """
    return Popen(["sft", "ssh", hostname, "--command", command], stderr=DEVNULL, stdout=DEVNULL, stdin=DEVNULL)


def await_puppet_runs(host: dict):
    """"""
    puppet_in_progress = True
    while puppet_in_progress:
        '''rc, out, err = run_remote_command(host, "sudo test -f /opt/puppetlabs/puppet/cache/agent_catalog_run.lock",
                                          raise_on_error=False)'''
        rc = run_remote_command(host, "sudo test -f /opt/puppetlabs/puppet/cache/agent_catalog_run.lock",
                                    type = 'background',
                                    raise_on_error=False)
        if rc == 0:
            time.sleep(10)
        else:
            puppet_in_progress = False


#def puppet_until(remote_command, instances: AWSStack, max_counter: int = None, primary_sh: str = None):
def puppet_until(remote_command, instances: AWSStack, max_counter: int = None):
    """Reruns Puppet on each instance until it detects kv-migrator is running,
    or until it fails to detect after [max_counter] times.

    Parameters
    ----------
    instances: AWSStack
        Stack to rerun Puppet on

    max_counter: int
        Number of times we should rerun if Puppet reports changes (optional, default = 5 * num_of_instances)
        
    primary_sh: str
        If passed, will check this node for kv success logs. Default is none.
    """

    import concurrent.futures
    import os
    
    thread_count = int(os.cpu_count() / 2)
    run_counter = 0
    if max_counter == None:
        max_counter = 20
    puppet_runs = []
    puppet_runs = list(instances.values())
    
    if remote_command == None:
        raise RuntimeError("You didn't specify an UNTIL in the code. The Code Owner is a moronic coder hacker person.")
    print_header("Getting setup for your Puppet run.... ")
    while len(puppet_runs) > 0:
        '''if primary_sh != None:
            rc_check = run_remote_command(instances[primary_sh],
                    remote_command,
                    type = 'background')
            #print(rc_check)
            if rc_check == 0:
                break
            else:
                print_info(f'Running puppet {run_counter} of {max_counter}')'''
        # Puppet exit codes
        #   0: The run succeeded with no changes or failures; the system was already in the desired state.
        #   1: The run failed, or wasn't attempted due to another run already in progress.
        #   2: The run succeeded, and some resources were changed.
        #   4: The run succeeded, and some resources failed.
        #   6: The run succeeded, and included both changes and failures.
        with concurrent.futures.ThreadPoolExecutor(max_workers=thread_count) as thp:
            run_puppet = {thp.submit(
                run_remote_command, instance, "sudo puppet agent -t", type = 'background'):
                    instance for instance in puppet_runs}
            for future in concurrent.futures.as_completed(run_puppet):
                host = run_puppet[future]
                try:
                    data=future.result()
                    if data in [0,2]:
                        #print(host)
                        rc_check = run_remote_command(host,
                        remote_command,
                        type = 'background')
                        if rc_check == 0:
                            puppet_runs.remove(host)
                            print_succ(f"Run {run_counter} of {max_counter} : puppet run {host.ssh_host} completed successfully with RC={data}")
                        else:
                            print_info(f'Run {run_counter} of {max_counter} : Still waiting on {host.ssh_host} to finish...')
                    else:
                        print_warning(f"Run {run_counter} of {max_counter} : rerunning puppet on {host.ssh_host} due to RC={data}")
                except Exception as e:
                    print_warning(f'Exception during puppet run on {host.ssh_host} during attempt: {run_counter} of {max_counter}. Exception: {e}')
        if run_counter >= max_counter:
            ##### rework message here
            print_warning('Please investigate Puppet running on this stack. Manual Intervention may be needed.')
            return False
        run_counter += 1
        time.sleep(30)

    return True
    
def rerun_puppet(instances: AWSStack, max_yellows: int = 1):
    """Reruns Puppet on each instance until it succeeds with no changes,
    or until it succeeds with changes [max_yellows] times.

    Parameters
    ----------
    instances: AWSStack
        Stack to rerun Puppet on

    max_yellows: int
        Number of times we should rerun if Puppet reports changes (optional, default 2)
    """
    yellows_per_host = {
        instance.ssh_host: 0 for instance in instances.instance_not_sh
    }

    puppet_runs = {
        instance.ssh_host: background_remote_command(instance.ssh_host, "sudo puppet agent -t")
        for instance in instances.instance_not_sh
    }
    while len(puppet_runs) > 0:
        time.sleep(1)
        new_runs = {}
        for host, process in puppet_runs.items():
            rc = process.poll()

            if rc is None:
                new_runs[host] = process
                continue
            elif rc == 0:
                print(f"Puppet run for {host} succeeded with no changes.")
                continue
            elif rc == 1:
                print(f"Puppet run failed for {host}, retrying in 10 seconds")
            elif rc == 2:
                yellows_per_host[host] += 1
                if yellows_per_host[host] >= max_yellows:
                    print(f"Puppet run for {host} succeeded with some changes, "
                          f"not rerunning it because we've already seen {yellows_per_host[host]} yellow runs")
                    continue
                else:
                    print(f"Puppet run for {host} succeeded with some changes (run #{yellows_per_host[host]}), "
                          "running it again in 10 seconds to ensure desired state")
            elif rc == 4:
                print(f"Puppet run for {host} succeeded with some failures, "
                      "running it again in 10 seconds to ensure desired state")
            elif rc == 6:
                print(f"Puppet run for {host} succeeded with some changes and some failures, "
                      "running it again in 10 seconds to ensure desired state")
            elif rc == 255:
                print(f"{host} is unresponsive, it has probably started migrating already. "
                      "Not rerunning Puppet on it.")
                continue
            else:
                print(f"Puppet run exited with unknown error code {rc} for {host}, retrying in 10 seconds")

            new_runs[host] = background_remote_command(host, "sleep 10 && sudo puppet agent -t")
        puppet_runs = new_runs
