import boto3
import subprocess
import os
import time
import re

try:
    from configparser import ConfigParser
except ImportError:
    from ConfigParser import ConfigParser  # ver. < 3.0
from getpass import getpass, getuser


class AWSInstance(object):
    """Represents a compute instance in AWS EC2

    Attributes
    ----------
    instance_id: str
        AWS-assigned ID for the instance

    instance_type: str
        Class and size of instance

    env: str
        Environment (dev/stg/lve) where instance is hosted

    role: str
        Function of the instance within the stack

    label: str
        CO2 label corresponding to instance

    fqdn: str
        Fully-qualified domain name for instance

    shc_label: str
        CO2 label for search head cluster, if this instance is part of one

    ssh_host: str
        Hostname used for connecting via SSH or ScaleFT

    region: str
        AWS region where instance is hosted

    Methods
    -------
    set_termination_protection(value: bool, account_id: str)
        Enables or disables termination protection on the instance
    """

    def __init__(self, instance_data: dict):
        """
        Parameters
        ----------
        instance_data: AWS API object containing instance attributes
        """
        self.instance_id = instance_data["InstanceId"]
        self.instance_type = instance_data["InstanceType"]
        self.ip = instance_data["PublicIpAddress"]
        self.vpc = instance_data["VpcId"]
        
        self.env = None
        self.role = None
        self.label = None
        self.fqdn = None
        self.shc_label = None

        for tag in instance_data["Tags"]:
            if tag["Key"] == "ServerEnv":
                self.env = tag["Value"]
            elif tag["Key"] == "Role":
                self.role = tag["Value"]
            elif tag["Key"] == "Label":
                self.label = tag["Value"]
            elif tag["Key"] == "FQDN":
                self.fqdn = tag["Value"]
            elif tag["Key"] == "Cluster":
                self.shc_label = tag["Value"]

        self.bastion = f"bastion.{self.vpc}.{self.env}.splunkcloud.systems"
        
        #self.ssh_host = self.fqdn.split(".")[0] if self.env in ["lve", "prod"] else self.fqdn
        self.ssh_host = self.fqdn.split(".")[0]
        self.region = instance_data["Placement"]["AvailabilityZone"][:-1]

    def set_termination_protection(self, value: bool, account_id: str):
        """
        Enables or disables termination protection on the instance

        Parameters
        ----------
        value: bool
            Whether or not termination protection should be enabled

        account_id: str
            AWS account ID for instance
        """
        session = boto3.Session(profile_name=account_id)
        ec2 = session.client("ec2", region_name=self.region)
        ec2.modify_instance_attribute(InstanceId=self.instance_id, DisableApiTermination={
            "Value": value
        })


class AWSStack(object):
    """Represents the instances of a stack hosted in AWS

    Attributes
    ----------
    indexers: List[AWSInstance]
        List of all indexers in the stack

    search_heads: Dict[str, AWSInstance]
        Standalone search heads, indexed by CO2 label

    search_head_clusters: Dict[str, List[AWSInstance]]
        List of search heads in each SHC, indexed by CO2 label of SHC

    inputs_data_managers: Dict[str, AWSInstance]
        IDMs, indexed by CO2 label

    all_instances: List[AWSInstance]
        List of all instances in the stack
    """

    def __init__(self, stack_name: str, aws_region: str, account_id: str):
        """
        Parameters
        ----------
        stack_name: str
            Name of CO2 stack

        aws_region: str
            Name of AWS region

        account_id: str
            AWS account ID
        """
        self.indexers = []
        self.search_heads = {}
        self.search_head_clusters = {}
        self.inputs_data_managers = {}
        self.all_instances = []
        self.instance_not_sh = []

        session = boto3.Session(profile_name=account_id)
        ec2 = session.client("ec2", region_name=aws_region)
        instance_pager = ec2.get_paginator("describe_instances")
        for page in instance_pager.paginate(Filters=[
            {
                "Name": "tag:Stack",
                "Values": [stack_name]
            },
            {
                "Name": "instance-state-name",
                "Values": [
                    "running"
                ]
            }
        ]):
            for reservation in page["Reservations"]:
                for instance_data in reservation["Instances"]:
                    instance = AWSInstance(instance_data)

                    self.all_instances.append(instance)

                    if instance.role == "cluster-master":
                        self.cluster_manager = instance
                    elif instance.role == "inputs-data-manager":
                        self.inputs_data_managers[instance.label] = instance
                    elif instance.role == "indexer":
                        self.indexers.append(instance)
                    elif instance.role == "search-head":
                        if instance.shc_label is not None:
                            if instance.shc_label not in self.search_head_clusters:
                                self.search_head_clusters[instance.shc_label] = []
                            self.search_head_clusters[instance.shc_label].append(instance)
                        else:
                            self.search_heads[instance.label] = instance
                self.instance_not_sh = [instance for instance in self.all_instances if instance.role != "search-head"]



def aws_login(account_id: str):
    """Logs into the specified AWS account using Okta credentials

    Parameters
    ----------
    account_id: str
        AWS account ID
    """
    USER = getuser()
    if account_id in ['377580395208', '390163525689', '930458123955']:
        powersre = 'power'
    else:
        powersre = 'sre'
    rolearn = f'arn:aws:iam::{account_id}:role/splunkcloud_account_{powersre}'

    now = int(time.time())
    PASWERD = getpass(prompt=f'AWS Login to SplunkCloud Okta for {USER} : ')
    login_cmd = ['okta-aws-login', '--role-arn', rolearn, '--mfa', 'push']
    p = subprocess.Popen(login_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, stdout=subprocess.PIPE,
                         universal_newlines=True)
    print('\n' + 'Approval request pushed to your device, waiting for authorization')
    aws_creds, stderr = p.communicate(input=PASWERD, timeout=60)

    now = int(time.time())
    time_to_expiration = 43200
    expires = (now + time_to_expiration)

    # Sanitizing the aws_creds string before writing it
    aws_creds = re.sub(";", "", aws_creds)
    aws_creds = re.sub("'", "", aws_creds)
    AWS_ACCESS_KEY_ID = re.search('AWS_ACCESS_KEY_ID.*', aws_creds).group(0).strip().split('=')[1]
    AWS_SECRET_ACCESS_KEY = re.search('AWS_SECRET_ACCESS_KEY.*', aws_creds).group(0).strip().split('=')[1]
    AWS_SESSION_TOKEN = re.search('AWS_SESSION_TOKEN.*', aws_creds).group(0).strip().split('=')[1]
    EXPIRES = f"{expires}\n"

    cred_file = f'/Users/{USER}/.aws/credentials'

    config = ConfigParser()

    try:
        os.makedirs(f'/Users/{USER}/.aws')
    except OSError:
        pass  # already exists

    try:
        open(cred_file)
    except FileNotFoundError:
        open(cred_file, "a")

    try:
        config.read(cred_file)
        config.get(account_id, 'expires')
    except:
        config.add_section(account_id)

    config.set(account_id, 'AWS_ACCESS_KEY_ID', AWS_ACCESS_KEY_ID)
    config.set(account_id, 'AWS_SECRET_ACCESS_KEY', AWS_SECRET_ACCESS_KEY)
    config.set(account_id, 'AWS_SESSION_TOKEN', AWS_SESSION_TOKEN)
    config.set(account_id, 'EXPIRES', EXPIRES)

    with open(cred_file, 'w+') as configfile:
        config.write(configfile)


def check_aws_login(account_id: str):
    """Ensures that we are logged into the specified AWS account

    Parameters
    ----------
    account_id: str
        AWS account ID
    """
    USER = getuser()
    config = ConfigParser()
    try:
        config.read(f'/Users/{USER}/.aws/credentials')
        loginNeeded = False
        if account_id in config:
            expires = int(config[account_id]['expires'])
            # if expires soon (30 minutes), then login
            if expires - 1800 < int(time.time()):
                loginNeeded = True
        else:
            loginNeeded = True
    except:
        loginNeeded = True

    if loginNeeded:
        aws_login(account_id)
