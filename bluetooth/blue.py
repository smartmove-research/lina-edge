#!/usr/bin/env python3
import asyncio
from dbus_next.aio import MessageBus
from dbus_next.constants import BusType
from dbus_next import Variant, DBusError

import logging



# Path to the local Bluetooth adapter
ADAPTER_PATH = '/org/bluez/hci0'
BLUEZ_SERVICE = 'org.bluez'

async def main():
    # Connect to the system D-Bus
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()

    # Introspect the adapter to ensure it exists
    try:
        adapter_xml = await bus.introspect(BLUEZ_SERVICE, ADAPTER_PATH)
    except DBusError as e:
        print(f'❌ Could not introspect adapter at {ADAPTER_PATH}:', e)
        return

    adapter_obj = bus.get_proxy_object(BLUEZ_SERVICE, ADAPTER_PATH, adapter_xml)
    adapter = adapter_obj.get_interface('org.bluez.Adapter1')

    # Start & stop discovery
    try:
        await adapter.call_start_discovery()
        print('🔍 Scanning for 5 seconds...')
        await asyncio.sleep(5)
        await adapter.call_stop_discovery()
    except DBusError as e:
        print('❌ Discovery error:', e)
        return

    # Get all managed objects (including devices)
    om_xml = await bus.introspect(BLUEZ_SERVICE, '/')
    manager = bus.get_proxy_object(BLUEZ_SERVICE, '/', om_xml).get_interface('org.freedesktop.DBus.ObjectManager')
    objects = await manager.call_get_managed_objects()

    TARGET_NAME = 'X-13'
    found = False

    # Iterate devices, handling missing properties gracefully
    for path, interfaces in objects.items():
        props = interfaces.get('org.bluez.Device1')
        if not props:
            continue

        name_prop = props.get('Name')
        addr_prop = props.get('Address')
        name = name_prop.value if name_prop else '(unknown)'
        addr = addr_prop.value if addr_prop else '(unknown)'
        print(f'• Found {name} [{addr}] at {path}')

        if name == TARGET_NAME:
            found = True
            device_xml = await bus.introspect(BLUEZ_SERVICE, path)
            device = bus.get_proxy_object(BLUEZ_SERVICE, path, device_xml).get_interface('org.bluez.Device1')
            try:
                print('🔗 Pairing…')
                await device.call_pair()
            except DBusError as e:
                if str(e) == "Already Exists":
                    print('✅ Paired - Skipped since device exist')
                else:
                    print('❌ Device operation failed:', e)
                    break
            try:
                
                print('🤝 Trusting…')
                await device.call_trust()
                print('✅ Trusted')
                print('🔌 Connecting…')
                await device.call_connect()
                print('✅ Connected!')
            except DBusError as e:
                print('❌ Device operation failed:', e)
            break

    if not found:
        print(f'⚠️ Device named "{TARGET_NAME}" not found.')

if __name__ == '__main__':
    asyncio.run(main())
