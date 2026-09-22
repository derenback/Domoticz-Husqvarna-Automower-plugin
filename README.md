# Domoticz-Husqvarna-Automower-plugin
Domoticz plugin for Husqvarna automowers.

A heavily reduced version of the original plugin by [FilipDem](https://github.com/FilipDem/Domoticz-Husqvarna-Automower-plugin).

The plugin monitors the status of your automower, including the battery status.

# Husqvarna API
This Husqvarna plugin makes use of the offical Husqvarna API. Consult [Husqvarna API](https://developer.husqvarnagroup.cloud/docs/get-started) for more information.

## Create an Husqvarna account
Please follow the instructions on [Signup](https://developer.husqvarnagroup.cloud/docs/get-started#1sign-up-and-create-account).

## Create the Domoticz application
Please follow the instructions on [Create Application](https://developer.husqvarnagroup.cloud/docs/get-started#2create-application) and use the following data:
* Application name: MyDomoticz
* Description: Husqvarna Application for Domoticz
* Redirect URL: http://localhost:8080

Connect then the Authentication API and Husqvarna Automower API by by using the button CONNECT NEW API.

On the developer site, you will find now a client_id (or application_id) and a client_secret (or an application_secret). Enter both in the settings of the Domoticz plugin hardware settings...

## Restrictions
* There is a restriction on the number of API calls by Husqvarna:
  * the quota is 21000 requests per week and appKey in total. That is 2 requests per minute for a week
  * the rate limit is 120 requests per minute and appKey
In theory we could now have a polling interval of every minute (which seems a bit overkill). Keep in mind that it is a change in policy as previously it was maximal 10000 calls per month. The plugin implements a light mechanism to slow down polling in the following cases.
  * all mowers are OFF
  * Husqvarna Cloud connection errors
  * Husqvarna returns that quota limit is achieved.

## Updating
When updating to the plugin supporting the Extended Plugin Framework, new devices are created. To keep the history, use the "replace" function from the GUI. Then all the history will be kept and all the references to the devices in scripts, groups, ... are also kept.


