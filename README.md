# kv-migrator

---
## Quick guide to migrate a stack

1. Install dependencies
```shell
python3 -m pip install -r requirements.txt
```
2. Run `kv-migrator.py`
3. Perform postchecks, and autoscaling if necessary, as shown in the [runbook](https://confluence.splunk.com/display/CLOUDOPS/Noah+Migration+Runbook)
---


## Auth
This script automatically prompts you to log into CO2, AWS, and Jira using Okta credentials.

## Usage
```
usage: kv-migrator.py [-h] -s STACK -t TICKET [-e ENV]

optional arguments:
  -h, --help            show this help message and exit
  -s STACK, --stack STACK
                        Stack name
  -t TICKET, --ticket TICKET
                        TO Jira number
  -e ENV, --env ENV     CO2 environment - dev, stg, lve/prod. Default is lve/prod.
  --skip_dt             disables the downtime of signal_FX and thruck
```

## Example Usage
```shell
python3 kv-migrator.py --stack my-stack --ticket TO-99999 --env lve
```

```
python3 kv-migrator.py -s rm-migrate -t TO-99999 -e lve --skip_dt
 --- Checking CO2 login ---
CO2 login
Enter password:
1. Okta push
2. Enter Okta token
Select MFA to use: 1
Created token
 --- Retrieving CO2 spec for rm-migrate in prod ---
AWS Login to SplunkCloud Okta for someuser :

Approval request pushed to your device, waiting for authorization
 --- This stack is hosted in AWS - us-east-1 ---
 --- Moving Jira ticket to START IMPLEMENTATION state ---
 --- Checking connectivity to search head instances ---
 >>>> ssh check on sh-i-02144e73e16602ee2 completed with RC=0 <<<<
 --- Found Primary SH hostname - sh-i-02144e73e16602ee2 ---
 --- Updating CO2 spec for rm-migrate in prod ---
 --- CO2 stack updated successfully. Review at https://web.co2.lve.splunkcloud.systems/stack/info/rm-migrate/proposals/ ---
 !!!! Waiting for CO2 change to be approved...  !!!!
 !!!! Running puppet 0 of 10 !!!!
 >>>> puppet run sh-i-02144e73e16602ee2 completed successfully with RC=2 <<<<
 --- KVservice-migration has started! ---
 !!!! Waiting on kvstore migration to complete, checking again in 30 seconds. !!!!
 !!!! Waiting on kvstore migration to complete, checking again in 30 seconds. !!!!
 --- Successful kvstore migration detected. Happy Happy Joy Joy. Please validate and close the ticket. ---
 --- Removing MW for rm-migrate in prod ---
 --- CO2 stack updated successfully. Review at https://web.co2.lve.splunkcloud.systems/stack/info/some-stack/proposals/ ---
 !!!! Waiting for CO2 change to be approved...  !!!!
 >>>> Script has completed. <<<<
```

