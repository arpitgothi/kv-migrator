import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from subprocess import Popen, PIPE, run
from typing import Set, Dict
import requests

from shared import CloudProvider, print_warning, print_info, print_error


def check_co2_login(env: str):
    """Ensures that we are logged into the given CO2 environment

    Parameters
    ----------
    env: str
        CO2 environment (dev/stg/lve)

    Raises
    ------
    RuntimeError
        If unable to log into CO2
    """
    now = time.time()
    home = Path.home()
    token_path = home.joinpath(".cloudctl").joinpath(f"token_{env}")

    try:
        mod_time = os.stat(token_path).st_mtime
        file_size = os.stat(token_path).st_size
    except:
        mod_time = 0
        file_size = 0

    p = subprocess.Popen(["cloudctl", "config", "show-context"], stdout=subprocess.PIPE)
    context, err = p.communicate()
    context = context.decode().strip()
    if context != env:
        subprocess.Popen(["cloudctl", "config", "use", env]).wait()

    file_age = now - mod_time
    if file_age > 14000 or file_size == 0:
        try:
            print("CO2 login")
            p = subprocess.Popen(["cloudctl", "auth", "login"])
            p.wait()
            rc = p.returncode
            if rc !=0:
                raise 
        except Exception as e:
            print_error(f'Unable to log in using "cloudctl auth login" ({e})')


def get_co2_spec(stack: str, env: str) -> dict:
    """Retrieves and parses the CO2 spec JSON for the given stack

    Parameters
    ----------
    stack: str
        Stack name

    Returns
    -------
    dict
        CO2 spec for stack
    """
    check_co2_login(env)
    p = subprocess.Popen(["cloudctl", "stacks", "get", stack, "-o", "json"], stdout=subprocess.PIPE)
    _spec, err = p.communicate()
    return json.loads(_spec)


def put_co2_spec(stack: str, ticket: str, spec: dict, message: str, env: str):
    """Submits a CO2 change request for the given stack

    Parameters
    ----------
    stack: str
        Stack name

    ticket: str
        Jira ticket number to reference

    spec: dict
        New CO2 spec

    message: str
        Description of changes
        
    env: str
        Environment

    Raises
    ------
    RuntimeError
        If CO2 rejects the updated spec
    """
    try:
        check_co2_login(env)
        p = subprocess.Popen([
            "cloudctl", "stacks", "update", stack, "--reason",
            f"{ticket} {message} (GENERATED BY KV-MIGRATION_AUTOMATION)", "-f", "-"
        ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        output, errs = p.communicate(input=json.dumps(spec))
        if "Update has been requested for" not in output:
            raise RuntimeError(output)
    except Exception as e:
        raise RuntimeError(f"Unable to write {stack} spec to CO2 - {e}")
    if env == ['lve', 'prod']:
        url = 'https://hooks.slack.com/services/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'
        message = f'PRAA: Automated KV Service Migration requested by @{os.environ.get("USER")} \n \
        https://web.co2.lve.splunkcloud.systems/stack/info/{stack}/proposals \n \
        https://splunk.atlassian.net/browse/{ticket}'
        try:
            r = requests.post(url, json={"text":message})
            if r.status_code != 200:
                print_warning(f'Automated slack bot failed please post this messages in #cloudworks-pr {message}')
            else:
                print_info('slack channel #cloudworks-pr has been updated with Merge request')
        except Exception as e:
            print_warning(e)


def get_co2_url(env: str, stack: str) -> str:
    """Gets the proper CO2 URL for the given stack in the given env

    Parameters
    ----------
    stack: str
        Stack name

    env: str
        CO2 environment (dev/stg/lve)

    Raises
    ------
    ValueError
        If the environment name is not recognized

    Returns
    -------
    str
        URL pointing to the "diff" view in CO2 for the given stack in the given env
    """
    if env == "dev":
        return f"https://web.co2.dev.splunkcloud.systems/stack/info/{stack}/proposals/"
    elif env == "stg":
        return f"https://web.stg.co2.splunkcloud.systems/stack/info/{stack}/proposals/"
    elif env in ["prod", "lve"]:
        return f"https://web.co2.lve.splunkcloud.systems/stack/info/{stack}/proposals/"
    else:
        raise ValueError(f"Environment {env} is not recognized.")


def get_stack_cloud_provider_and_region(spec: dict) -> (CloudProvider, str):
    """Parses the CO2 spec to determine which cloud (AWS/GCP/Azure) and region the stack is hosted in

    Parameters
    ----------
    spec: dict
        CO2 spec for stack

    Returns
    -------
    Tuple(CloudProvider, str)
        Cloud provider and region for stack
    """
    if "cloud" in spec["spec"]:
        _cloud = CloudProvider(spec["spec"]["cloud"])
    else:
        _cloud = CloudProvider.AWS

    _region = spec["spec"]["region"]
    _account_id = spec["status"]["provisionerOutput"]["account_id"]
    return _cloud, _region, _account_id


def get_primary_search_head_name(spec: dict) -> str:
    """Gets the CO2 label for the primary search head or SHC in the stack

    Parameters
    ----------
    spec: dict
        CO2 spec for stack

    Raises
    ------
    ValueError
        If the primary search head couldn't be found in the spec

    Returns
    -------
        CO2 label of primary SH/SHC
    """
    if "searchHeadCluster" in spec["spec"]:
        if spec["spec"]["searchHeadCluster"].get("primary"):
            return spec["spec"]["searchHeadCluster"]["name"]

    if "searchHeads" in spec["spec"]:
        for search_head in spec["spec"]["searchHeads"]:
            if search_head.get("primary"):
                return search_head["name"]

    raise ValueError("Cannot find primary search head in spec!")


def await_jenkins_job(stack: str, env: str):
    """Waits for completion of the Jenkins job for the stack

    Parameters
    ----------
    stack: str
        Stack name
    """
    jenkins_done = False
    max_checks = 60
    checks = 0
    while not jenkins_done:
        time.sleep(10)
        spec = get_co2_spec(stack, env)
        if "status" in spec \
                and "lastProvisionedStatus" in spec["status"] \
                and spec["status"]["lastProvisionedStatus"] == "Complete":
            jenkins_done = True
        else:
            checks += 1
            if checks >= max_checks:
                print("Didn't receive completion signal from Jenkins after 10 minutes")
                input("Please ensure that the Jenkins job is completed, then hit enter")
                jenkins_done = True


def get_assisted_app_ids() -> Set[int]:
    """Gets the set of app IDs that cannot be converted to SSAI, based on the apps.json file in the Puppet control repo

    Raises
    ------
    RuntimeError
        If there is an issue retrieving or parsing the apps.json file from Git

    Returns
    -------
    Set[int]
        Set of app IDs that must remain as assisted-install
    """
    assisted_app_ids = []

    with tempfile.TemporaryDirectory() as control_repo_path:
        print("Fetching the control repo")
        clone_p = Popen([
            "git", "clone", "--depth", "1", "--no-checkout",
            "git@cd.splunkdev.com:cloudworks/puppet/control-repo", control_repo_path
        ], stdout=PIPE, stderr=PIPE)
        clone_out, clone_err = clone_p.communicate()
        if clone_p.returncode != 0:
            print(clone_err)
            raise RuntimeError("Failed to fetch the Puppet control repo!")

        print("Retrieving the premium apps list")
        show_p = Popen([
            "git", "--no-pager", "--git-dir", Path(control_repo_path).joinpath(".git"), "show",
            "main:site/cloudworks/files/noah-apps-migration/apps.json"
        ], stdout=PIPE, stderr=PIPE)
        show_out, show_err = show_p.communicate()
        if show_p.returncode != 0:
            print(show_err)
            raise RuntimeError("Failed to get the apps.json file from the repo!")

        apps_file: Dict = json.loads(show_out)

        premium_apps: Dict[Dict[str]] = apps_file.get("premium_apps", {})
        # Retrieve every listed component of every premium app
        for premium_app_name, premium_app_dict in premium_apps.items():
            for component_name, component_ids in premium_app_dict.items():
                for component in component_ids.split(","):
                    assisted_app_ids.append(int(component))

        other_non_ssaible_apps: Dict[str] = apps_file.get("other_non_ssaible_apps", {})
        for app_ids in other_non_ssaible_apps.values():
            for app_id in app_ids.split(","):
                assisted_app_ids.append(int(app_id))

    return set(assisted_app_ids)

def get_cloudctl_history(stack: str, env: str, specVersion: int):
    check_co2_login(env)
    co2_stacks_history = ['cloudctl', 'stacks', 'history', stack, '-o', 'json']
    p = run(co2_stacks_history, capture_output=True)
    if json.loads(p.stdout) == []:
        print_warning('\n' + 'Spec history NOT found in CO2 for stack "' + stack + '" in environment ' + env)
        print_warning('Did you use the correct Stack name?')
        raise RuntimeError
    try:
        historyVersion = json.loads(p.stdout)[-1]['version']
        historyCheck = json.loads(p.stdout)[-1]['state']
    except IndexError as e:
        print_warning(e)
        raise RuntimeError
    #checking if Approved or blank (for dev/stg/(new?) stacks)
    if specVersion == None or historyVersion == specVersion + 1:
        versionCheck = True
    elif historyVersion == specVersion:
        print_warning('Did the CO2 change get rejected?')
        raise RuntimeError('Did the CO2 change get rejected?')
    else:
        versionCheck = False
    if historyCheck in ['Approved', ''] and versionCheck:
        return True
    else:
        return False