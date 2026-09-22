#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Small Domoticz helpers used by the monitoring-only Husqvarna plugin."""

from datetime import datetime
from enum import IntEnum
from pathlib import Path
from typing import Any, Dict, Optional
import traceback

try:
    import DomoticzEx as Domoticz
except ImportError:
    Domoticz = None


class DomoticzConstants(IntEnum):
    """Constants used by the plugin lifecycle."""

    TIMEDOUT = 1
    MINUTE = 6


DeviceCollection = Dict[str, Any]


def dump_config_to_log(parameters: Dict[str, str], devices: DeviceCollection) -> None:
    """Log plugin parameters and the current Domoticz devices."""
    for parameter, value in parameters.items():
        if value:
            Domoticz.Debug(f'Parameter {parameter}: {value}')

    Domoticz.Debug(f'Got {len(devices)} devices:')
    for index, (device_name, device) in enumerate(devices.items()):
        Domoticz.Debug(f'{index} Device name:     {device_name}')
        Domoticz.Debug(f'{index} Device ID:       {device.DeviceID}')
        Domoticz.Debug(f'{index} Device got {len(device.Units)} units:')
        for unit_index, unit_number in enumerate(device.Units):
            unit = device.Units[unit_number]
            Domoticz.Debug(f'{index}.{unit_index} Unit number:    {unit_number}')
            Domoticz.Debug(f'{index}.{unit_index} Unit name:      {unit.Name}')
            Domoticz.Debug(f'{index}.{unit_index} Unit nValue:     {unit.nValue}')
            Domoticz.Debug(f'{index}.{unit_index} Unit sValue:     {unit.sValue}')
            Domoticz.Debug(f'{index}.{unit_index} Unit LastLevel:  {unit.LastLevel}')


def update_device(
    always_update: bool,
    devices: DeviceCollection,
    device_id: str,
    unit: int,
    n_value: Optional[int] = None,
    s_value: Optional[str] = None,
    **kwargs: Any
) -> bool:
    """Update a Domoticz unit and any supplied device properties."""
    update_standard = update_properties = update_options = False

    device = devices.get(device_id)
    unit_obj = device.Units.get(unit) if device else None
    if unit_obj is None:
        Domoticz.Debug(f'Device with DeviceID/Unit {device_id}/{unit} does not exist... No update done...')
        return False

    n_value = unit_obj.nValue if n_value is None else n_value
    s_value = unit_obj.sValue if s_value is None else s_value

    if always_update or unit_obj.nValue != int(n_value) or unit_obj.sValue != str(s_value):
        unit_obj.nValue = int(n_value)
        unit_obj.sValue = str(s_value)
        update_standard = True

    for property_name in ('Image', 'BatteryLevel', 'SignalLevel', 'Used'):
        if property_name in kwargs and kwargs[property_name] is not None:
            if getattr(unit_obj, property_name) != kwargs[property_name]:
                setattr(unit_obj, property_name, kwargs[property_name])
                update_properties = True

    if 'Options' in kwargs and kwargs['Options'] and unit_obj.Options != kwargs['Options']:
        unit_obj.Options = kwargs['Options']
        update_options = True

    if update_standard or update_properties or update_options:
        unit_obj.Update(UpdateProperties=update_properties, UpdateOptions=update_options)
    else:
        unit_obj.Touch()

    if device.TimedOut:
        device.TimedOut = 0

    Domoticz.Debug(
        f'Request to update device with AlwaysUpdate={always_update}; '
        f'DeviceID={device_id}; Unit={unit}; nValue={n_value}; sValue={s_value}; '
        f'others={kwargs}. Updates done: standard={update_standard}, '
        f'properties={update_properties}, options={update_options}.'
    )
    return update_standard or update_properties or update_options


def timeout_device(
    devices: DeviceCollection,
    device_id: Optional[str] = None,
    timed_out: int = DomoticzConstants.TIMEDOUT
) -> None:
    """Set one device, or all devices, to Domoticz timeout status."""
    selected_devices = devices.items() if device_id is None else (
        [(device_id, devices[device_id])] if device_id in devices else []
    )
    for name, device in selected_devices:
        if device.TimedOut != timed_out:
            device.TimedOut = timed_out
            Domoticz.Debug(f'Device ID {device.DeviceID or name} set to timeout {bool(timed_out)}.')


def get_unit(devices: DeviceCollection, device_id: str, unit: int) -> Any:
    """Return a Domoticz unit, or ``None`` if it does not exist."""
    device = devices.get(device_id)
    return device.Units.get(unit) if device else None


def log_backtrace_error(parameters: Dict[str, str]) -> None:
    """Append the current exception traceback to the plugin log file."""
    log_path = Path(parameters['HomeFolder']) / f"{parameters['Name']}_traceback.txt"
    with log_path.open('a') as log_file:
        log_file.write(f'-General Error-{datetime.now()}------------------\n')
        log_file.write(traceback.format_exc())
        log_file.write('---------------------------------\n')


TIMEDOUT = DomoticzConstants.TIMEDOUT
MINUTE = DomoticzConstants.MINUTE


__all__ = [
    'DomoticzConstants',
    'TIMEDOUT',
    'MINUTE',
    'dump_config_to_log',
    'update_device',
    'timeout_device',
    'get_unit',
    'log_backtrace_error',
]
