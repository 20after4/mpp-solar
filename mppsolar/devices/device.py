import abc
import importlib
import logging

from ..io.testio import TestIO

log = logging.getLogger("MPP-Solar")

PORT_TYPE_UNKNOWN = 0
PORT_TYPE_TEST = 1
PORT_TYPE_USB = 2
PORT_TYPE_ESP32 = 4
PORT_TYPE_SERIAL = 8
PORT_TYPE_JKBLE = 16
PORT_TYPE_ASYNCSERIAL = 32


class AbstractDevice(metaclass=abc.ABCMeta):
    """
    Abstract device class
    """

    def __init__(self, *args, **kwargs):
        self._protocol = None
        self._protocol_class = None
        self._port = None
        log.debug(f"{self._classname} __init__ args {args}")
        log.debug(f"{self._classname} __init__ kwargs {kwargs}")
        self._name = kwargs["name"]
        self.set_port(**kwargs)
        self.set_protocol(**kwargs)
        log.debug(
            f"{self._classname} __init__ name {self._name}, port {self._port}, protocol {self._protocol}"
        )

    def __str__(self):
        """
        Build a printable representation of this class
        """
        return f"{self._classname} device - name: {self._name}, port: {self._port}, protocol: {self._protocol}"

    def get_port_type(self, port):
        if port is None:
            return PORT_TYPE_UNKNOWN

        port = port.lower()
        # check for test type port
        if "test" in port:
            log.debug("device:get_port_type: port matches test")
            return PORT_TYPE_TEST
        # async serial
        elif "asyncserial" in port:
            log.debug("device:get_port_type: port matches asyncserial")
            return PORT_TYPE_ASYNCSERIAL
        # USB type ports
        elif "hidraw" in port:
            log.debug("device:get_port_type: port matches hidraw")
            return PORT_TYPE_USB
        elif "mppsolar" in port:
            log.debug("device:get_port_type: port matches mppsolar")
            return PORT_TYPE_USB
        # ESP type ports
        elif "esp" in port:
            log.debug("device:get_port_type: port matches esp")
            return PORT_TYPE_ESP32
        # JKBLE type ports
        elif ":" in port:
            # all mac addresses currently return as JKBLE
            log.debug("device:get_port_type: port matches jkble ':'")
            return PORT_TYPE_JKBLE
        elif "jkble" in port:
            log.debug("device:get_port_type: port matches jkble")
            return PORT_TYPE_JKBLE
        elif "serial" in port:
            log.debug("device:get_port_type: port matches serial")
            return PORT_TYPE_SERIAL
        elif "ttyusb" in port:
            log.debug("device:get_port_type: port matches ttyusb")
            return PORT_TYPE_SERIAL
        else:
            return PORT_TYPE_UNKNOWN

    def set_protocol(self, protocol=None, **kwargs):
        """
        Set the protocol for this device
        """
        log.debug(f"device.set_protocol with protocol {protocol}")
        if protocol is None:
            self._protocol = None
            self._protocol_class = None
            return
        protocol_id = protocol.lower()
        # Try to import the protocol module with the supplied name (may not exist)
        try:
            proto_module = importlib.import_module("mppsolar.protocols." + protocol_id, ".")
        except ModuleNotFoundError:
            log.error(f"No module found for protocol {protocol_id}")
            self._protocol = None
            self._protocol_class = None
            return
        # Find the protocol class - classname must be the same as the protocol_id
        try:
            self._protocol_class = getattr(proto_module, protocol_id)
        except AttributeError:
            log.error(f"Module {proto_module} has no attribute {protocol_id}")
            self._protocol = None
            self._protocol_class = None
            return
        # Instantiate the class
        # TODO: fix protocol instantiate
        self._protocol = self._protocol_class("init_var", proto_keyword="value", second_keyword=123)

    def set_port(self, port=None, baud=2400, portoveride=None, **kwawgs):
        if portoveride:
            log.info(f"Port overide: using port: {portoveride}")
            port_type = self.get_port_type(portoveride)
        else:
            port_type = self.get_port_type(port)
        if port_type == PORT_TYPE_TEST:
            log.info("Using testio for communications")
            from mppsolar.io.testio import TestIO

            self._port = TestIO()
        elif port_type == PORT_TYPE_USB:
            log.info("Using hidrawio for communications")
            from mppsolar.io.hidrawio import HIDRawIO

            self._port = HIDRawIO(device_path=port)
        elif port_type == PORT_TYPE_ESP32:
            log.info("Using esp32io for communications")
            from mppsolar.io.esp32io import ESP32IO

            self._port = ESP32IO(device_path=port)
        elif port_type == PORT_TYPE_JKBLE:
            log.info("Using jkbleio for communications")
            from mppsolar.io.jkbleio import JkBleIO

            self._port = JkBleIO(device_path=port)
        elif port_type == PORT_TYPE_SERIAL:
            log.info("Using serialio for communications")
            from mppsolar.io.serialio import SerialIO

            self._port = SerialIO(device_path=port, serial_baud=baud)
        elif port_type == PORT_TYPE_ASYNCSERIAL:
            log.info("Using asyncserialio for communications")
            from mppsolar.io.asyncserialio import AsyncSerialIO

            self._port = AsyncSerialIO(device_path=port, serial_baud=baud)

        else:
            self._port = None

    def list_commands(self):
        # print(f"{'Parameter':<30}\t{'Value':<15} Unit")
        if self._protocol is None:
            log.error("Attempted to list commands with no protocol defined")
            return {"ERROR": ["Attempted to list commands with no protocol defined", ""]}
        result = {}
        for command in self._protocol.COMMANDS:
            result[command] = [self._protocol.COMMANDS[command]["description"], ""]
        return result

    def list_outputs(self):
        import pkgutil

        pkgpath = __file__
        pkgpath = pkgpath[: pkgpath.rfind("/")]
        pkgpath += "/../outputs"
        print(pkgpath)
        result = []
        for _, name, _ in pkgutil.iter_modules([pkgpath]):
            # print(name)
            _module_class = importlib.import_module("mppsolar.outputs." + name, ".")
            _module = getattr(_module_class, name)
            result.append(_module())

        return result

    def run_commands(self, commands) -> dict:
        """
        Run multiple commands sequentially
        :param commands: List of commands to run, either with or without an alias.
        If an alias is provided, it will be substituted in place of cmd name in the returned dict
        Additional elements in the tuple will be passed to run_command as ordered
        Example: ['QPIWS', ...] or [('QPIWS', 'ALIAS'), ...] or [('QPIWS', 'ALIAS', True), ...] or mix and match
        :return: Dictionary of responses
        """
        responses = {}
        for i, command in enumerate(commands):
            if isinstance(command, str):
                responses[command] = self.run_command(command)
            elif isinstance(command, tuple) and len(command) > 0:
                if len(command) == 1:  # Treat as string
                    responses[command[0]] = self.run_command(command[0])
                elif len(command) == 2:
                    responses[command[1]] = self.run_command(command[0])
                else:
                    responses[command[1]] = self.run_command(command[0], *command[2:])
            else:
                responses["Command {:d}".format(i)] = {
                    "ERROR": ["Unknown command format", "(Indexed from 0)"]
                }
        return responses

    def run_command(self, command, show_raw=False) -> dict:
        """
        generic method for running a 'raw' command
        """
        log.info(f"Running command {command}")

        if self._protocol is None:
            log.error("Attempted to run command with no protocol defined")
            return {"ERROR": ["Attempted to run command with no protocol defined", ""]}
        if self._port is None:
            log.error(f"No communications port defined - unable to run command {command}")
            return {
                "ERROR": [
                    f"No communications port defined - unable to run command {command}",
                    "",
                ]
            }

        # Send command and receive data
        full_command = self._protocol.get_full_command(command)
        log.info(f"full command {full_command} for command {command}")

        # JkBleIO is very different from the others, only has protocol jk02 and jk04, maybe change full_command?
        # if isinstance(self._port, JkBleIO):
        # need record type, SOR
        #    raw_response = self._port.send_and_receive(command, self._protocol)

        # Band-aid solution, can't really segregate TestIO from protocols w/o major rework of TestIO
        if isinstance(self._port, TestIO):
            raw_response = self._port.send_and_receive(
                full_command, self._protocol.get_command_defn(command)
            )
        else:
            raw_response = self._port.send_and_receive(full_command)
        log.debug(f"Send and Receive Response {raw_response}")

        # Handle errors; dict is returned on exception
        # Maybe there should a decode for ERRORs and WARNINGS...
        if isinstance(raw_response, dict):
            return raw_response

        # Decode response
        decoded_response = self._protocol.decode(raw_response, show_raw, command)
        log.debug(f"Decoded response {decoded_response}")
        log.info(f"Decoded response {decoded_response}")

        return decoded_response

    def get_status(self, show_raw) -> dict:
        # Run all the commands that are defined as status from the protocol definition
        data = {}
        for command in self._protocol.STATUS_COMMANDS:
            data.update(self.run_command(command))
        return data

    def get_settings(self, show_raw) -> dict:
        # Run all the commands that are defined as settings from the protocol definition
        data = {}
        for command in self._protocol.SETTINGS_COMMANDS:
            data.update(self.run_command(command))
        return data

    def run_default_command(self, show_raw):
        return self.run_command(command=self._protocol.DEFAULT_COMMAND, show_raw=show_raw)
