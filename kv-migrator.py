#!/usr/bin/env python3
from distutils.log import error
#from re import search
from shared import CloudProvider, parse_args, print_header, print_warning, print_info, print_succ, print_error, script_exit, \
    script_pre_req_check, time_table, py_ver_check
from shared.co2 import check_co2_login, get_co2_spec, put_co2_spec, get_co2_url, get_stack_cloud_provider_and_region, \
    get_cloudctl_history
from shared.git_puller import git_puller, shc_testing
from shared.ssh import run_remote_command, puppet_until, rerun_puppet
from shared.aws import AWSStack, check_aws_login
from shared.downtime import downtime_thruk, downtime_sfx
from shared.jira import start_implementation
from packaging import version
import os
import concurrent.futures
from time import sleep, perf_counter
import datetime
#import getpass


def check_kvservice_migration(spec: dict, kv_features_spec: dict, search_nodes: list, sh_feature_flag: dict, kv_platform_spec: list) -> bool:
    if "featureFlags" in spec["spec"]:
        kv_features_status = kv_features_spec.items() <= spec["spec"]["featureFlags"].items()

        sh_check = {}
        for search_node in search_nodes:
            for node in spec["spec"]["searchHeads"]:
                sh_index = spec["spec"]["searchHeads"].index(node)
                if "count" in spec["spec"]["searchHeads"][sh_index] and spec["spec"]["searchHeads"][sh_index]["count"] == 0:
                    continue
                if search_node == spec["spec"]["searchHeads"][sh_index]["name"] or search_node == "all":
                    if "featureFlags" in spec["spec"]["searchHeads"][sh_index] and \
                      sh_feature_flag.items() <= spec["spec"]["searchHeads"][sh_index]["featureFlags"].items():
                        sh_check[sh_index] = True
                    else:
                        sh_check[sh_index] = False
        # This check found: https://www.geeksforgeeks.org/python-test-if-all-values-are-same-in-dictionary/ Method #2
        if len(list(set(list(sh_check.values())))) == 1 and set(list(sh_check.values())) == {True}:
            sh_feature_status = True
        else:
            sh_feature_status = False

        if "platformSettings" in spec["spec"]:
            kv_platform_status = all(item in spec["spec"]["platformSettings"].keys() for item in kv_platform_spec)
        else:
            kv_platform_status = False

        if kv_features_status and sh_feature_status and kv_platform_status:
            return True

    return False

def backout_co2(stack, ticket, spec, changed_nodes, original_featureFlags, scriptname, env, shash):
    # if the original feature flags had external kvstore, use them, else set it to false
    if 'external_kvstore_enabled' in original_featureFlags:
        spec["spec"]["featureFlags"].update(original_featureFlags)
    else:
        kv_features_spec = {'external_kvstore_enabled' : False, 'ec_scs_enabled' : False}
        spec["spec"]["featureFlags"].update(kv_features_spec)
    sh_feature_flag = {'auto_kvstore_to_external_migration_enabled' : False}
    for changed_node in changed_nodes:
        #SHC section, future ready
        if 'shc' in changed_node:
            if 'searchHeadCluster' in spec['spec'] and "size" in spec["spec"]["searchHeadCluster"] and spec['spec']['searchHeadCluster']['size'] != 0:
                spec["spec"]["searchHeadCluster"]["featureFlags"].update(sh_feature_flag)
            continue
        for node in spec["spec"]["searchHeads"]:
            sh_index = spec["spec"]["searchHeads"].index(node)
            if changed_node == spec["spec"]["searchHeads"][sh_index]["name"]:
                spec["spec"]["searchHeads"][sh_index]["featureFlags"].update(sh_feature_flag)

    put_co2_spec(stack, ticket, spec, f"Backing out KVservice migration. Executing {scriptname} version={shash}", env)
    print_header(f"CO2 stack updated successfully. Review at {get_co2_url(env, stack)}")
    while True:
        if get_cloudctl_history(stack, env, spec['version']):
            break
        else:
            print_info('Waiting for CO2 change to be approved... ')
        sleep(30)

def set_mw(spec: dict):
    spec['spec']['maintenanceWindow'] = {
        "ranges": [
            {
                "startTime": "00:00",
                "duration": "23h59m"
            }
        ],
        "days": [
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday"
        ]
    }

def unset_mw(spec: dict):
    spec['spec']['maintenanceWindow'] = {}

def main():
    py_ver_check()
    start_time = perf_counter()
    scriptname = os.path.basename(__file__)
    stack, ticket, env, skip_dt, search_nodes, backout = parse_args()
    shash = git_puller()
    shc_enabled = shc_testing()
    start_date = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    if not skip_dt:
        sfx_env = script_pre_req_check(env)

    print_header("Checking CO2 login")
    check_co2_login(env)

    print_header(f"Retrieving CO2 spec for {stack} in {env}")
    if get_cloudctl_history(stack, env, None):
        spec = get_co2_spec(stack, env)
    else:
        print_error("There is a pending CO2 change. Please review before beginning, then try again.")

    #Sanity checks for provided search_nodes
    # if user provided any that do not exist, we will fail to ensure the user knows what they are doing.
    if 'all' not in search_nodes:
        search_node_spec_list = spec["spec"]["searchHeads"]
        if "searchHeadCluster" in spec["spec"] and spec["spec"]["searchHeadCluster"] != {}:
            search_node_spec_list.append(spec["spec"]["searchHeadCluster"])
        sh_names = []
        for node_spec in search_node_spec_list:
            sh_names.append(node_spec['name'])
        for search_node in search_nodes:
            if search_node not in sh_names:
                print_error(f'User specifed node "{search_node}" does not exist, Please re-confirm the stack and input list and try again...')
            else:
                if 'shc' in search_node:
                    if not shc_enabled:
                        print_error("Search Head Clusters are not supported at this time. Please review the request and documentation.")
                    #shc should be last in the list, since it was added last...
                    if search_node_spec_list[-1]['size'] == 0:
                        print_error(f"Your input defined name has an SHC, for which the size is ZERO...\n Please confirm your stack and input list and try again...")
                else:
                    try:
                        for node_spec in search_node_spec_list:
                            if node_spec['name'] == search_node and node_spec['count'] == 0 :
                                print_error(f'User specifed node "{search_node}" has the count is ZERO...\n Please confirm your stack and input list and try again..."')
                    except KeyError:
                        if search_node != 'sh1':
                            print_error(f'User specified node "{search_node}" does not have a defined count...? is this normal? exiting...')                        
    else:
        if not shc_enabled:
            if 'searchHeadCluster' in spec['spec'] and spec["spec"]["searchHeadCluster"] != {} and spec['spec']['searchHeadCluster']['size'] != 0:
                print_error("Search Head Cluster detected. SHCs are not supported at this time. Please review the request and documentation.")
    minimum_version = "8.2.2109"

    if version.parse(spec['spec']['releaseInfo']['splunkVersion']) < version.parse(minimum_version):
        print_error(f"{stack} Splunk Version is below {minimum_version} and can not be migrated to KV Service.")
    
    kv_features_spec = {'scs_tokens_enabled' : True, 'external_kvstore_enabled' : True, 'ec_scs_enabled' : True}
    sh_feature_flag = {'auto_kvstore_to_external_migration_enabled' : True}
    kv_platform_spec = {'scs_environment' : f'{stack}.api.scs.splunk.com', 'scs_tenant' : stack}
    # Flags to enable if ES
    kv_features_spec_ES = {'mvl_enabled' : True, 'collection_cache_enabled' : True}
    kv_platform_spec_ES = {'kvstore_collection_cache' : 'indexer', 'kvstore_collection_cache_timeout' : 5}

    if env == 'dev':
        kv_platform_spec = {'scs_environment' : f'{stack}.api.playground.scs.splunk.com', 'scs_tenant' : stack}
    if env == 'stg':
        kv_platform_spec = {'scs_environment' : f'{stack}.api.staging.scs.splunk.com', 'scs_tenant' : stack}
        
    #if 'searchHeadCluster' in spec["spec"] and spec["spec"]["searchHeadCluster"] != {}:
    #    print_error("This stack has Search Head Clustering, which is not supported by this script.")

    premium_apps = {}
    # ES enabled on stack...
    if 'premiumApps' in spec["spec"] and spec["spec"]["premiumApps"]["enterpriseSecurity"] != {}:
        premium_apps.update({'enterpriseSecurity' : True})
    # All premium apps are current listed as exit conditions.
    for p_app in ["enterpriseSecurity", "enterpriseSecurityPCICP", "itsi", "pci", "stream", "vmware"]:
        if 'premiumApps' in spec["spec"] and spec["spec"]["premiumApps"][p_app] != {}:
            premium_apps.update({p_app : True})
            print_error(f"This stack has Premium App: {p_app}, which is not supported by this script. ")
        else:
            premium_apps.update({p_app : False})
            
    cloud, region, account_id = get_stack_cloud_provider_and_region(spec)
    check_aws_login(account_id)
    print_header(f"This stack is hosted in {cloud.name} - {region}")
    if cloud != CloudProvider.AWS:
        print_error("Only AWS stacks are supported for now.")
    
    if check_kvservice_migration(spec, kv_features_spec, search_nodes, sh_feature_flag, kv_platform_spec) and not os.environ.get("SKIP_GIT_CHECK") == "1":
        print_succ("This stack has already been configured for kvservice.")
        time_table(start_time)
        script_exit(0)
    
    #commenting out backout flag option. steps to be updated for reverse migration, and not a rollback    
    #if backout:
    #    backout_co2(stack, ticket, spec, scriptname, env, shash)
    
    if not skip_dt:
        print_header('Adding Downtime in Thruk')
        downtime_thruk(stack, ticket, "add")
        print_header('Adding Downtime in SignalFX')
        downtime_sfx(sfx_env, stack, "create", ticket)
    
    
    if env=='prod':
        print_header("Moving Jira ticket to START IMPLEMENTATION state")
        #start_implementation(ticket)

    instances = AWSStack(stack, region, account_id)
    print(f"{stack} - {region} - {account_id}")


    if "featureFlags" not in spec["spec"]:
        spec["spec"]["featureFlags"] = {}
    if "platformSettings" not in spec["spec"]:
        spec["spec"]["platformSettings"] = {}
    original_featureFlags = {}
    original_featureFlags.update(spec["spec"]["featureFlags"])
    spec["spec"]["featureFlags"].update(kv_features_spec)
    spec["spec"]["platformSettings"].update(kv_platform_spec)
    if premium_apps['enterpriseSecurity']:
        spec["spec"]["featureFlags"].update(kv_features_spec_ES)
        spec["spec"]["platformSettings"].update(kv_platform_spec_ES)
    changed_nodes = []
    for search_node in search_nodes:
        for node in spec["spec"]["searchHeads"]:
            setFeatureFlag = False
            sh_index = spec["spec"]["searchHeads"].index(node)
            if "count" in spec["spec"]["searchHeads"][sh_index] and spec["spec"]["searchHeads"][sh_index]["count"] == 0:
                continue
            if search_node == 'all':
                setFeatureFlag = True
            elif search_node == spec["spec"]["searchHeads"][sh_index]["name"]:
                setFeatureFlag = True
            if setFeatureFlag:
                changed_nodes.append(spec["spec"]["searchHeads"][sh_index]["name"])
                if "featureFlags" not in spec["spec"]["searchHeads"][sh_index]:
                    spec["spec"]["searchHeads"][sh_index]["featureFlags"] = {}
                spec["spec"]["searchHeads"][sh_index]["featureFlags"].update(sh_feature_flag)
        #SHC is disabled until later, as this is unsupported
        if 'shc' in search_node or search_node in ['all']:
            if 'searchHeadCluster' in spec['spec'] and "size" in spec["spec"]["searchHeadCluster"] and spec['spec']['searchHeadCluster']['size'] != 0:
                changed_nodes.append(spec["spec"]["searchHeadCluster"]["name"])
                if "featureFlags" not in spec["spec"]["searchHeadCluster"]:
                    spec["spec"]["searchHeadCluster"]["featureFlags"] = {}
                spec["spec"]["searchHeadCluster"]["featureFlags"].update(sh_feature_flag)

    if len(changed_nodes) == 0:
        print_error(f"There will be no changes to any active Search Heads, please check try again...\nPlease check on SFX Downtime if not re-running.")
    set_mw(spec)


    print_header("Checking connectivity to search head instances")
    #ssh_failure = False
    all_search_nodes = instances.search_heads
    # No harm is adding an empty dictionary since SHC is disabled above, future ready for when SHC is enabled.
    if 'all' in search_nodes or any('shc' in node for node in search_nodes):
        for label in instances.search_head_clusters:
            for shc_node in instances.search_head_clusters[label]:
                shc_node_label = label + '-' + str(instances.search_head_clusters[label].index(shc_node))
                all_search_nodes.update({shc_node_label : shc_node})
            
    sh_nodes = {}
    if search_nodes == ['all']:
        sh_nodes = all_search_nodes
    else:
        for sh_instance in all_search_nodes.keys():
            if all_search_nodes[sh_instance].label in search_nodes:
                sh_nodes[sh_instance] = all_search_nodes[sh_instance]
    with concurrent.futures.ThreadPoolExecutor(int(os.cpu_count() / 2)) as thp:
        ssh_check = {thp.submit(
            run_remote_command,
            instance,
            'echo "Connected to `hostname`"',
            type = 'background'):
                instance for instance in list(sh_nodes.values())}
        for future in concurrent.futures.as_completed(ssh_check):
            try:
                host=ssh_check[future]
                data=future.result()
                if data == 0:
                    print_succ(f"ssh check on {host.ssh_host} completed with RC={data}")
                else:
                    print_error(f"ssh check on {host.ssh_host} failed with RC={data}")
            except Exception as e:
                print_error(f'Exception occurent during ssh check on  {host.ssh_host}. Exception: {e}')


    #!#$%^^&#%^&!!!!!!!!!!!!!!!!
    ### need to remember why we even care about the primary sh here...
    #!#$%^^&#%^&!!!!!!!!!!!!!!!!

        ### possible above is to check for kv mig logs to determine success...? 
        ###  if that is all, then we should abandon that and check all passed nodes for success
        ###   then pull them from the 'to-do' list

        #### determinted that we don't need the primary SH at all... commenting it out.

    
    '''if 'all' in search_nodes:
        primary_sh_name = get_primary_search_head_name(spec)
    else:
        #if not all, arbitrary picking first in the list, as primary may or may not be specified.
        primary_sh_name = search_nodes[0]
    
    if 'shc' in primary_sh_name:
        for sh_key in sh_nodes.keys():
            if 'shc' in sh_key:
                ## Getting the first shc in the list for no reason other than it is easy to get this node
                primary_sh_host = sh_nodes[sh_key]
                break
    else:
        primary_sh_host = sh_nodes[primary_sh_name]
    print_header(f"Found Primary SH hostname - {primary_sh_host.ssh_host}")
    print_header(f"Will use this SH - {primary_sh_host.ssh_host}")'''
    
    #script_exit(0)

    print_header(f"Updating CO2 spec for {stack} in {env}")
    put_co2_spec(stack, ticket, spec, f"Preparing for KVservice migration. Executing {scriptname} version={shash}", env)
    print_header(f"CO2 stack updated successfully. Review at {get_co2_url(env, stack)}")

    #Waiting for CO2 change to be approved...
    while True:
        if get_cloudctl_history(stack, env, spec['version']):
            break
        else:
            print_info('Waiting for CO2 change to be approved... ')
        sleep(30)
    print_header("Checking for status on instances...")
    #get new spec just in case need to rollback... 
    spec = get_co2_spec(stack, env)
    print_header("Running Puppet on instances except SHs...")
    rerun_puppet(instances)
    remote_command = f"sudo journalctl --since '{start_date}' | egrep kvstore-external-migrate-script | egrep -v '\[\/.*\]|msg=audit|grep' | egrep '(migration_backup__)'"
    #puppet_until(remote_command, sh_nodes, primary_sh = primary_sh_name)
    if not puppet_until(remote_command, sh_nodes):
        script_exit("Not ready to move forward.")
    print_header('KVservice-migration has started!')
    shnode_success = {}
    shnode_list = list(sh_nodes.values())
    while True:
        with concurrent.futures.ThreadPoolExecutor(int(os.cpu_count() / 2)) as thp:
            status_check = {thp.submit(
                run_remote_command,
                instance,
                f"sudo journalctl --since '{start_date}' | egrep kvstore-external-migrate-script | egrep -v '\[\/.*\]|msg=audit|grep'",
                type = 'run',
                raise_on_error = False):
                    instance for instance in shnode_list}
            for future in concurrent.futures.as_completed(status_check):
                host = status_check[future]
                try:
                    status_rc, status_output, status_error = future.result()
                    if status_rc !=0:
                        raise RuntimeWarning(status_error)
                    if 'main=>PASS' in status_output:
                        print_info(f"Migration success detected on {host.ssh_host}")
                        shnode_success.update({host.label: True})
                        shnode_list.remove(host)
                    if 'main=>FAIL' in status_output:
                        print_warning(f"Migration failure detected on {host.ssh_host}")
                        shnode_success.update({host.label: False})
                        shnode_list.remove(host)
                except Exception as e:
                    print_warning(f'Exception during status check on {host.ssh_host}. Exception: {e}')
        if len(shnode_list) == 0:
            break
        print_info('Waiting on kvstore migration to complete, checking again in 30 seconds.')
        sleep(30)
    if False in list(shnode_success.values()):
        print_warning('Failure detected, rolling back CO2 changes.')
        backout_co2(stack, ticket, spec, changed_nodes, original_featureFlags, scriptname, env, shash)
        #sleeping 45 seconds to wait for CO2 changes to get into puppet
        sleep(45)
        print_header('Running puppet on SH to Chnage defaultKVStoreType to local')
        remote_command = 'sudo /opt/splunk/bin/splunk btool server list kvstore --debug | grep "defaultKVStoreType.*=.*local"'
        #puppet_until(remote_command, sh_nodes, primary_sh = primary_sh_name)
        puppet_until(remote_command, sh_nodes)
        print_header('KVservice-migration has been rolled back!')
        spec = get_co2_spec(stack, env)
    else:
        remote_command = 'sudo /opt/splunk/bin/splunk btool server list kvstore --debug | grep "defaultKVStoreType.*=.*external"'
        print_header('Running puppet on SH to Chnage defaultKVStoreType to external')
        puppet_until(remote_command, sh_nodes)
        print_header('defaultKVStoreType = external detected')
        print_header('Successful kvstore migration detected. Happy Happy Joy Joy. Please validate and close the ticket.')

    unset_mw(spec)
    print_header(f"Removing MW for {stack} in {env}")
    put_co2_spec(stack, ticket, spec, f"Removing MW. Executing {scriptname} version={shash}", env)
    print_header(f"CO2 stack updated successfully. Review at {get_co2_url(env, stack)}")
    #Waiting for CO2 change to be approved...
    while True:
        if get_cloudctl_history(stack, env, spec['version']):
            break
        else:
            print_info('Waiting for CO2 change to be approved... ')
        sleep(30)
    if not skip_dt:
        downtime_thruk(stack, ticket, "remove")
        downtime_sfx(sfx_env, stack, "delete", ticket)
    print_succ('Script has completed.')
    time_table(start_time)
    script_exit(0)
        
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt as e:
        print("")
        print_info('Ctrl+C detected. Thanks for using our script. Have a good day. :)')
        script_exit(e)
