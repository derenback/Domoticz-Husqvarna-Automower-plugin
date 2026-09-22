#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Husqvarna Mower Plugin for Domoticz

This plugin integrates Husqvarna robotic lawn mowers with Domoticz home automation system.
It provides monitoring of mower status, battery level, and next schedule.

Original author: Filip Demaertelaere, modified to only log by David Derenbäck

"""

# Standard imports
import sys
import os
import datetime
import threading
import queue
from typing import Dict, Optional, Any
from enum import Enum, IntEnum

# Add the parent directory to the path for Domoticz imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

# Domoticz imports
import DomoticzEx as Domoticz
from domoticzEx_tools import (
    DomoticzConstants, dump_config_to_log, update_device, timeout_device,
    get_unit, log_backtrace_error
)

# Local imports
import Husqvarna

# XML plugin configuration
"""
<plugin key="Husqvarna" name="Husqvarna" author="Derenback" version="0.0.1">
    <description>
        <h2>Husqvarna</h2>
        <p>The Husqvarna plugin for Domoticz provides seamless integration with your Husqvarna robotic lawnmowers. Leveraging the official Husqvarna API, this plugin allows you to monitor your mower's status. It creates virtual devices for each connected mower, offering real-time insights into its activity and battery level.</p>
        <br/>
        <h2>Key features</h2>
        <ul>
            <li><b>Real-time Status Monitoring:</b> View your mower's current state (e.g., mowing, charging, parked, paused, off).</li>
            <li><b>Battery Level Indication:</b> Keep track of your mower's battery percentage.</li>
            <li><b>Next Schedule:</b> Shows the next upcoming scheduled mowing session.</li>
        </ul>
        <br/>
        <h2>Hardware Plugin Configuration</h2>
        <ul>
            <li><b>Client_id:</b> Your Husqvarna API client ID (also known as application ID). Obtain this from the Husqvarna Developer Portal: <a href="https://developer.husqvarnagroup.cloud/applications">https://developer.husqvarnagroup.cloud/applications</a>. You will need to create an application to get these credentials.</li>
            <li><b>Client_secret:</b> Your Husqvarna API client secret (also known as application secret). Obtain this from the Husqvarna Developer Portal, linked to your application. This should be kept confidential.</li>
            <li><b>Update interval:</b> The frequency, in minutes, at which the plugin will poll the Husqvarna API for status updates. A smaller interval means more frequent updates. The current restrictions mentioned on the Husqvarna Developer Portal are a rate limit of 120 requests per minute and a quota of 21000 requests per week (2 requests per minute for a week). Please note that if all configured mowers are detected as 'OFF' (e.g., during winter storage), the plugin will automatically reduce this polling interval to once per hour to minimize unnecessary API calls and save resources. Normal polling resumes when a mower becomes active again.</li>
            <li><b>Debug:</b> Select the level of debugging information to be logged to the Domoticz log. "None" is recommended for normal operation, while other options provide more detailed logs for troubleshooting and development.</li>
        </ul>
    </description>
    <params>
        <param field="Mode1" label="Client_id" width="250px" required="true" default=""/>
        <param field="Mode2" label="Client_secret" width="250px" required="true" default="" password="true"/>
        <param field="Mode5" label="Update interval" width="120px" required="true" default="2"/>
        <param field="Mode6" label="Debug" width="120px">
            <options>
                <option label="None" value="0" default="true"/>
                <option label="Python Only" value="2"/>
                <option label="Basic Debugging" value="62"/>
                <option label="Basic+Messages" value="126"/>
                <option label="Queue" value="128"/>
                <option label="Connections Only" value="16"/>
                <option label="Connections+Queue" value="144"/>
                <option label="All" value="-1"/>
            </options>
        </param>
    </params>
</plugin>
"""

class UnitId(IntEnum):
    """Unit identifiers for Husqvarna mower devices in Domoticz."""
    STATE = 1
    BATTERY = 2
    NEXT_SCHEDULE = 4

class DeviceText(str, Enum):
    """Text identifiers for device names."""
    STATE = 'State'
    BATTERY = 'Battery Level'
    NEXT_SCHEDULE = 'Next Schedule'

class ImageIdentifier(str, Enum):
    """Custom image identifiers for Husqvarna mower devices."""
    STANDARD = 'Husqvarna'
    OFF = 'HusqvarnaOff'

class UpdateSpeed(IntEnum):
    """Status update speed modes for the plugin."""
    NORMAL = 0
    LIMITS_EXCEEDED = 2
    ALL_OFF = 3
    SYSTEM_ERROR = 4

class HusqvarnaAction(str, Enum):
    """Monitoring actions used by the queue."""
    LOGIN = 'Login'
    GET_MOWERS = 'GetMowers'
    GET_STATUS = 'GetStatus'

class HusqvarnaPlugin:
    """Main plugin class for Husqvarna mower integration with Domoticz."""
    
    def __init__(self) -> None:
        """Initialize the plugin with default values."""
        self.run_again = DomoticzConstants.MINUTE
        self.stop_requested = False
        self.speed_status = UpdateSpeed.NORMAL
        self.system_retries = 0
        self.husqvarna_api: Optional[Husqvarna.Husqvarna] = None
        self.tasks_queue = queue.Queue()
        self.tasks_thread = threading.Thread(
            name='QueueThread', 
            target=self._handle_tasks,
            daemon=True
        )

    def on_start(self) -> None:
        """Handle the plugin startup process."""
        Domoticz.Debug('onStart called')

        # Setup debugging if enabled
        self._setup_debugging()
        
        # Ensure custom images are available
        self._create_custom_images()
        
        # Start background task thread
        self.tasks_thread.start()
        
        # Initialize API and get mower data
        self.tasks_queue.put({'Action': HusqvarnaAction.LOGIN.value})
        self.tasks_queue.put({'Action': HusqvarnaAction.GET_MOWERS.value})
        self.tasks_queue.put({'Action': HusqvarnaAction.GET_STATUS.value})

    def _setup_debugging(self) -> None:
        """Set up debugging based on plugin parameters."""
        if Parameters["Mode6"] != '0':
            try:
                Domoticz.Debugging(int(Parameters["Mode6"]))
                dump_config_to_log(Parameters, Devices)
            except Exception:
                pass

    def _create_custom_images(self) -> None:
        """Create custom images for the mower devices if not already available."""
        for image_id in [image.value for image in ImageIdentifier]:
            if image_id not in Images:
                Domoticz.Image(f'{image_id}.zip').Create()
                Domoticz.Debug(f"Created {image_id} image")

    def on_stop(self) -> None:
        """Handle the plugin shutdown process."""
        Domoticz.Debug('onStop called')
        self.stop_requested = True

        # Discard work queued behind the task currently being processed.
        while True:
            try:
                self.tasks_queue.get_nowait()
                self.tasks_queue.task_done()
            except queue.Empty:
                break

        # Signal the worker to exit after its current API request.
        self.tasks_queue.put(None)

        if self.tasks_thread and self.tasks_thread.is_alive():
            self.tasks_thread.join(timeout=10)
            if self.tasks_thread.is_alive():
                Domoticz.Error('Queue thread did not stop before the shutdown timeout.')

        Domoticz.Debug('Plugin stopped')

    def on_connect(self, connection: Any, status: int, description: str) -> None:
        """Handle connection events."""
        Domoticz.Debug(f'onConnect called ({connection.Name}) with status={status}')

    def on_message(self, connection: Any, data: Dict) -> None:
        """Handle message events."""
        Domoticz.Debug(f"onMessage called: {connection.Name} - {data['Status']}")

    def on_disconnect(self, connection: Any) -> None:
        """Handle disconnection events."""
        Domoticz.Debug(f'onDisconnect called ({connection.Name})')

    def on_heartbeat(self) -> None:
        """
        Handle heartbeat events.
        This is called regularly by Domoticz and is used to:
        1. Retry API initialization if needed
        2. Refresh mower list periodically
        3. Update mower status
        4. Adjust polling frequency based on mower status
        """
        if self.stop_requested:
            return

        self.run_again -= 1
        if self.run_again <= 0:
            # If API not initialized, try to login
            if self.husqvarna_api is None:
                self.tasks_queue.put({'Action': HusqvarnaAction.LOGIN.value})
            
            # Refresh mower list daily
            now = datetime.datetime.now()
            if (self.husqvarna_api and 
                self.husqvarna_api.get_timestamp_last_update_mower_list() and
                self.husqvarna_api.get_timestamp_last_update_mower_list() + datetime.timedelta(days=1) < now):
                self.tasks_queue.put({'Action': HusqvarnaAction.GET_MOWERS.value})
                
            # Update mower status
            self.tasks_queue.put({'Action': HusqvarnaAction.GET_STATUS.value})

    def _adjust_update_frequency(self) -> None:
        """
        Adjust the update frequency based on:
        1. Errors from Husqvarna Cloud
        2. API rate limits
        3. Whether all mowers are off
        4. Going home
        """
        if self.system_retries > 5:
            # Too many errors from Husqvarna server received
            self.run_again = 180 * DomoticzConstants.MINUTE

            if self.speed_status != UpdateSpeed.SYSTEM_ERROR:
                Domoticz.Status(f'Reduce status update speed to {self.run_again/DomoticzConstants.MINUTE} minutes because of too many errors from Husqvarna Cloud.')
                self.speed_status = UpdateSpeed.SYSTEM_ERROR
                
        elif self.husqvarna_api and self.husqvarna_api.are_api_limits_reached():
            # API limits reached - slow down significantly
            self.run_again = 30 * DomoticzConstants.MINUTE
            
            if self.speed_status != UpdateSpeed.LIMITS_EXCEEDED:
                Domoticz.Status(f'Reduce status update speed to {self.run_again/DomoticzConstants.MINUTE} minutes as Husqvarna API limits are reached!')
                self.speed_status = UpdateSpeed.LIMITS_EXCEEDED
                
        elif self.husqvarna_api and self.husqvarna_api.mowers and self.husqvarna_api.are_all_mowers_off():
            # (only in case there are mowers in the list) All mowers off - check once per hour
            self.run_again = 60 * DomoticzConstants.MINUTE
            
            if self.speed_status != UpdateSpeed.ALL_OFF:
                Domoticz.Status(f'Reduce status update speed to {self.run_again/DomoticzConstants.MINUTE} minutes as all Husqvarna mowers are off.')
                self.speed_status = UpdateSpeed.ALL_OFF

        elif self.husqvarna_api and any(
            mower.get('activity', '') == 'GOING_HOME'
            for mower in self.husqvarna_api.mowers
            if isinstance(mower, dict)
        ):
            self.run_again = DomoticzConstants.MINUTE
            # No specific speed_status change for this, it's a temporary boost
            Domoticz.Debug(f"Increasing update speed to {self.run_again / DomoticzConstants.MINUTE} minutes as a mower is going home.")
        
        else:
            # Normal operation - use configured interval
            configured_interval_minutes = float(Parameters.get('Mode5', '1').replace(',','.'))
            self.run_again = DomoticzConstants.MINUTE * configured_interval_minutes
            
            if self.speed_status != UpdateSpeed.NORMAL:
                Domoticz.Status(f'Re-establish normal update speed to {self.run_again/DomoticzConstants.MINUTE} minutes.')
                self.speed_status = UpdateSpeed.NORMAL

    def _handle_tasks(self) -> None:
        """
        Background thread to handle API tasks.
        This runs in a separate thread to prevent blocking the main Domoticz thread
        during potentially slow API operations.
        """
        Domoticz.Debug('Entering tasks handler')
            
        while True:
            try:
                # Get task from queue (blocking)
                task = self.tasks_queue.get(block=True)
                    
                # Exit signal received
                if task is None:
                    Domoticz.Debug('Exiting task handler')
                    try:
                        if self.husqvarna_api:
                            self.husqvarna_api.close()
                            self.husqvarna_api = None
                    except AttributeError:
                        pass
                    break
                        
                # Process the task
                Domoticz.Debug(f"Handling task: {task['Action']} (parameters: {task}).")
                self._process_task(task)

            except queue.Empty:
                pass # Continue loop if queue is empty 
            except Exception as e:
                Domoticz.Error(f"Unexpected error in task handler: {e}")
                log_backtrace_error(Parameters)
                   
            finally:
                # Mark task as done
                if 'task' in locals():
                    self.tasks_queue.task_done()
                    del task

    def _process_task(self, task: Dict[str, Any]) -> None:
        """
        Process a task from the queue.
        Args:
            task: The task dictionary with action and parameters
        """
        action = task['Action']
        
        # Handle login
        if action == HusqvarnaAction.LOGIN.value:
            self._handle_login_task()

        else:
            # Handle mower list retrieval
            if action == HusqvarnaAction.GET_MOWERS.value:
                self._handle_get_mowers_task()

            # Handle status update
            elif action == HusqvarnaAction.GET_STATUS.value:
                self._handle_get_status_task()

            # Dynamic adaptation of update frequency
            self._adjust_update_frequency()

    def _handle_login_task(self) -> None:
        """
        Handle API login task.
        Uses bool(api) which calls __bool__ on the Husqvarna object,
        which returns self.state.authenticated set during __init__.
        """
        Domoticz.Debug("Log in to Husqvarna API.")
        # Ensure Husqvarna instance is re-created on each login attempt for fresh state if needed
        self.husqvarna_api = Husqvarna.Husqvarna(Parameters['Mode1'], Parameters['Mode2'])
        if self.husqvarna_api:
            self.system_retries = 0
            Domoticz.Debug("Successfully logged in to Husqvarna API.")
        else:
            error = self.husqvarna_api.get_http_error() if self.husqvarna_api is not None else 'Unknown'
            Domoticz.Error(f"Unable to get credentials from Husqvarna Cloud: {error}")
            self.system_retries += 1
            timeout_device(Devices)

    def _handle_get_mowers_task(self) -> None:
        """Handle retrieving the list of mowers."""
        Domoticz.Debug("Retrieving the list of mowers.")
        if self.husqvarna_api:
            if self.husqvarna_api.get_mowers():
                self.system_retries = 0
                current_mowers = { mower['name'] for mower in self.husqvarna_api.mowers }
                for mower_name in current_mowers:
                    # Create devices if they don't exist
                    self._create_mower_devices(mower_name)
            else:
                Domoticz.Error(f"Error getting list of mowers from Husqvarna Cloud: {self.husqvarna_api.get_http_error()}")
                self.system_retries += 1
                timeout_device(Devices)

    def _handle_get_status_task(self) -> None:
        """Handle retrieving current status for all mowers."""
        Domoticz.Debug("Retrieving current status for all mowers.")
        if self.husqvarna_api: 
            if self.husqvarna_api.get_mowers_info():
                self.system_retries = 0
                if not self.husqvarna_api.mowers:
                    Domoticz.Error("No Husqvarna mowers available from the Husqvarna Cloud.")
                    self.system_retries += 1
                    timeout_device(Devices)
                for mower in self.husqvarna_api.mowers:
                    self._update_mower_devices(mower)
            else:
                Domoticz.Error(f"Error getting detailed status of mowers: {self.husqvarna_api.get_http_error()}")
                self.system_retries += 1
                timeout_device(Devices)

    def _update_mower_devices(self, mower: Dict[str, Any]) -> None:
        """
        Update or create Domoticz devices for a mower.
        Args:
            mower: Dictionary with mower information
        """
        Domoticz.Debug(f'Status information received from Husqvarna Cloud: {mower}')

        # Name of mower
        mower_name = mower['name']
                
        # Determine image based on mower state
        image = Images[ImageIdentifier.OFF.value].ID if mower.get('state') == Husqvarna.State.OFF.name else Images[ImageIdentifier.STANDARD.value].ID
        
        # Update state text
        state_text = self._format_state_text(mower)
        update_device(False, Devices, mower_name, UnitId.STATE, 0, state_text, Image=image)
        
        # Update battery level
        update_device(False, Devices, mower_name, UnitId.BATTERY, mower.get('battery_pct', 0), str(mower.get('battery_pct', 0)), Image=image)

        # Update next schedule
        schedule_text = self._format_next_schedule_text(mower)
        update_device(False, Devices, mower_name, UnitId.NEXT_SCHEDULE, 0, schedule_text, Image=image)

    def _format_state_text(self, mower: Dict[str, Any]) -> str:
        """Format the state text based on mower state, activity, and error."""
        error_state = mower.get('error_state', '')
        state = mower.get('state', '')
        activity = mower.get('activity', '')
        restricted_reason = mower.get('restricted_reason', '')

        state_str = getattr(Husqvarna.State, state, Husqvarna.State.UNKNOWN).value
        activity_str = getattr(Husqvarna.Activity, activity, Husqvarna.Activity.UNKNOWN).value
        restricted_reason_str = getattr(Husqvarna.PlannerRestrictedReason, restricted_reason, Husqvarna.PlannerRestrictedReason.NONE).value

        base_str = f"{state_str}: {activity_str}" if activity != Husqvarna.Activity.NOT_APPLICABLE.name else f"{state_str}"

        if error_state:
            return f"{base_str}\n<body><p style=\"line-height:80%;font-size:80%;\">{error_state.strip()}</p></body>"

        else:
            if restricted_reason:
                return f"{base_str}\n<body><p style=\"line-height:80%;font-size:80%;\">{restricted_reason_str}</p></body>"
            else:
                return base_str

    def _format_next_schedule_text(self, mower: Dict[str, Any]) -> str:
        """
        Format the next scheduled mowing session as readable text.
        Uses nextStartTimestamp from the Husqvarna planner API (milliseconds).
        Note: Husqvarna API returns local time in the timestamp, not UTC.
        utcfromtimestamp is used intentionally to avoid double timezone conversion.
        """
        planner = mower.get('planner', {})
        timestamp_ms = planner.get('next_start_timestamp', None)
        restricted_reason = planner.get('restricted_reason', '')

        # Default value
        result = 'No schedule'

        # No schedule available 
        if not timestamp_ms:
            return result

        # Schedule available
        try:
            # Husqvarna API provides timestamp in local time despite being milliseconds epoch.
            # utcfromtimestamp avoids applying an additional local timezone offset.
            slot_dt = datetime.datetime.utcfromtimestamp(timestamp_ms / 1000)
            now = datetime.datetime.now()

            if slot_dt.date() == now.date():
                day_label = 'Today'
            elif slot_dt.date() == (now + datetime.timedelta(days=1)).date():
                day_label = 'Tomorrow'
            else:
                day_label = slot_dt.strftime('%A')

            result = f'{day_label} {slot_dt.strftime("%H:%M")}'

            if restricted_reason is not Husqvarna.PlannerRestrictedReason.NONE.name:
                if ( reason_text := getattr(Husqvarna.PlannerRestrictedReason, restricted_reason, Husqvarna.PlannerRestrictedReason.NONE).value ):
                    result += f"\n<body><p style=\"line-height:80%;font-size:80%;\">{reason_text}</p></body>"

        except Exception as e:
            Domoticz.Debug(f"Error formatting schedule text: {e}")

        return result

    def _create_mower_devices(self, mower_name: str) -> None:
        """
        Create Domoticz devices for a mower.
        Args:
            mower_name: Name of the mower
        """
        new_device_created = False

        # State text display
        if not get_unit(Devices, mower_name, UnitId.STATE):
            Domoticz.Unit(
                DeviceID=mower_name, 
                Unit=UnitId.STATE, 
                Name=f"{Parameters['Name']} - {mower_name} - {DeviceText.STATE.value}", 
                TypeName='Text', 
                Image=Images[ImageIdentifier.STANDARD.value].ID, 
                Used=1
            ).Create()
            new_device_created = True
        
        # Battery level
        if not get_unit(Devices, mower_name, UnitId.BATTERY):
            Domoticz.Unit(
                DeviceID=mower_name, 
                Unit=UnitId.BATTERY, 
                Name=f"{Parameters['Name']} - {mower_name} - {DeviceText.BATTERY.value}", 
                TypeName='Custom', 
                Options={'Custom': '0;%'}, 
                Image=Images[ImageIdentifier.STANDARD.value].ID, 
                Used=1
            ).Create()
            new_device_created = True

        # Next schedule text device
        if not get_unit(Devices, mower_name, UnitId.NEXT_SCHEDULE):
            Domoticz.Unit(
                DeviceID=mower_name,
                Unit=UnitId.NEXT_SCHEDULE,
                Name=f"{Parameters['Name']} - {mower_name} - {DeviceText.NEXT_SCHEDULE.value}",
                TypeName='Text',
                Image=Images[ImageIdentifier.STANDARD.value].ID,
                Used=1
            ).Create()
            new_device_created = True
        
        # Set all devices as timed out until we get real data
        if new_device_created: 
            timeout_device(Devices, device_id=mower_name)

# Global plugin instance
_plugin = HusqvarnaPlugin()

def onStart():
    global _plugin
    _plugin.on_start()

def onStop():
    global _plugin
    _plugin.on_stop()

def onConnect(Connection, Status, Description):
    global _plugin
    _plugin.on_connect(Connection, Status, Description)

def onMessage(Connection, Data):
    global _plugin
    _plugin.on_message(Connection, Data)

def onDisconnect(Connection):
    global _plugin
    _plugin.on_disconnect(Connection)

def onHeartbeat():
    global _plugin
    _plugin.on_heartbeat()
