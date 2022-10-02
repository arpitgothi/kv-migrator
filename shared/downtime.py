from git.remote import add_progress
from shared import print_warning, print_error
from shared.ssh import ca_host_ssh
from getpass import getuser
from subprocess import Popen, PIPE

def downtime_thruk(stack: str, ticket: str, mode: str):
    username = getuser()
    success = False
    while not success:
        '''rc, out, err = run_remote_command("cloud-ansible-us-east-1.splunkcloud.com", (
            f"nagios_host_downtime_edit.py "
            f"--mode add --duration 240 --group {stack} "
            f"--user {username} --comment '{ticket} KV Store Migration'"
        ), raise_on_error=False)'''
        rc, out, err = ca_host_ssh(
            (f"nagios_host_downtime_edit.py "
            f"--mode {mode} --duration 240 --group {stack} "
            f"--user {username} --comment '{ticket} KV Store Migration'")
        )

        if rc == 0:
            print("Downtime added successfully.")
            success = True
        elif "no host found" in out:
            print("Stack is not enrolled in Thruk, skipping downtime")
            success = True
        elif "socket.error" in err:
            print("Failed to connect to Thruk.")
            raise ConnectionError()
        else:
            print(out)
            print(err)
            print_warning("Failed to add downtime in Thruk!")
            print_error("Please manually add DT in monitoring, and re-run script with --skip_dt flag")

def downtime_sfx(sfx_env: str, stack: str, action: str, ticket: str):
    sfx_params = ['sfx-cli', 'mute', '-e', sfx_env, action, stack]
    if action == 'create':
        sfx_params.extend(['-d', '240', '-r', f'"{ticket} KV Store Migration"'])
    #print(sfx_params)
    p = Popen(sfx_params, stdout=PIPE, stderr=PIPE, stdin=PIPE)
    out, err = p.communicate()
    if err:
        return err
    return out.decode()
