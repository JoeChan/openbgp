# Copyright 2015 Cisco Systems, Inc.
# All rights reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

""" BGP Open message"""

import struct
from ipaddr import IPv4Address

from openbgp.common import exception as excp
from openbgp.common import constants as bgp_cons


class Open(object):
    """
    After a TCP connection is established, the first message sent by each
    side is an OPEN message. If the OPEN message is acceptable, a
    KEEPALIVE message confirming the OPEN is sent back
    """

    def __init__(self, version=None, asn=None, hold_time=None,
                 bgp_id=None, opt_para_len=None, opt_paras=None):

        """
        :param version: BGP Protocol version.
        :param asn: AS number.
        :param hold_time: Hold time
        :param bgp_id: BGP Router ID
        :param opt_para_len: Optional Parameters length
        :param opt_paras: Optional Parameters
        """
        # 1-octet
        # +-----------+
        # | Version   |
        # +-----------+-----------+
        # | My Autonomous System  |
        # +-----------+-----------+
        # |       Hold Time       |
        # +-----------+-----------+-----------+-----------+
        # |                BGP Identifier                 |
        # +-----------+-----------+-----------+-----------+
        # |OptParm Len|
        # +-----------+-----------+-----------+-----------+
        # | Optional Parameters (variable)                |
        # +-----------+-----------+-----------+-----------+

        self.version = version
        self.asn = asn
        self.hold_time = hold_time
        self.bgp_id = bgp_id
        self.opt_para_len = opt_para_len
        self.opt_paras = opt_paras

        self.capa_dict = {
            'AFI_SAFI': [],
            '4byteAS': False,
            'routeRefresh': False,
            'ciscoRouteRefresh': False,
            'GracefulRestart': False,
            'ciscoMultiSession': False
        }
        # used to store Capabilities {code: value}

    def parse(self, message):

        """Parses a BGP Open message"""

        try:
            self.version, self.asn, self.hold_time, \
                self.bgp_id, self.opt_para_len = struct.unpack('!BHHIB', message[:10])

        except:
            raise excp.MessageHeaderError(
                sub_error=bgp_cons.ERR_MSG_HDR_BAD_MSG_LEN,
                data=message[:10])

        self.bgp_id = IPv4Address(self.bgp_id).__str__()

        if self.version != 4:
            # Here we just support BGP-4
            raise excp.OpenMessageError(
                sub_error=bgp_cons.ERR_MSG_OPEN_UNSUP_VERSION,
                data=self.version)

        if isinstance(self.asn, float):
            self.asn = str(self.asn).split('.')
            self.asn = 65536 * (int(self.asn[0])) + int(self.asn[1])

        if self.asn in (0, 2 ** 16 - 1):
            # bad peer asn
            raise excp.OpenMessageError(
                sub_error=bgp_cons.ERR_MSG_OPEN_BAD_PEER_AS,
                data=self.asn)
        # Hold Time negotiation is out of this scope

        if self.bgp_id in (0, 2 ** 32 - 1):
            raise excp.OpenMessageError(
                sub_error=bgp_cons.ERR_MSG_OPEN_BAD_BGP_ID,
                data=self.bgp_id)
        # Optional Parameters
        if self.opt_para_len:

            self.opt_paras = message[10:]

            # While Loop: Parse one Optional Parameter(Capability) each time
            while self.opt_paras:

                # 1 octet     1 octet      variable
                # --------------------------------------+
                # para_type | para_length | para_value |
                # --------------------------------------+
                opt_para_type, opt_para_length = struct.unpack('!BB', self.opt_paras[:2])

                # Parameter Type 1: Authentication (deprecated) [RFC4271] [RFC5492]
                # Parameter Type 2: Capabilities [RFC5492]
                # Here we only support Type 2
                if opt_para_type != 2:
                    # if type is not type 2, return an suberror used to Notification
                    raise excp.OpenMessageError(
                        sub_error=bgp_cons.ERR_MSG_OPEN_UNSUP_OPT_PARAM,
                        data=message[10:])

                # ----------------------  Parse Capabilities ------------------#
                # capabilities belongs to one Optional Parameter Capability
                capabilities = self.opt_paras[2:opt_para_length + 2]

                while capabilities:

                    # ---- Parse every capability in this Optional Parameter
                    capability = Capability()
                    capability.parse(capabilities)

                    # (1) for 4 bytes ASN
                    if capability.capa_code == capability.FOUR_BYTES_ASN:
                        asn = struct.unpack('!I', capability.capa_value)[0]
                        self.asn = asn
                        self.capa_dict['4byteAS'] = True

                    # (2) Multiprotocol Extensions for BGP-4
                    elif capability.capa_code == capability.MULTIPROTOCOL_EXTENSIONS:
                        afi, res, safi = struct.unpack('!HBB', capability.capa_value)
                        self.capa_dict['AFI_SAFI'].append((afi, safi))

                    # (3) Route Refresh
                    elif capability.capa_code == capability.ROUTE_REFRESH:
                        self.capa_dict['routeRefresh'] = True

                    # (4) Cisco Route Refresh
                    elif capability.capa_code == capability.CISCO_ROUTE_REFRESH:
                        self.capa_dict['ciscoRouteRefresh'] = True

                    # (5) Graceful Restart
                    elif capability.capa_code == capability.GRACEFUL_RESTART:
                        self.capa_dict['GracefulRestart'] = True

                    # (6) Cisco MultiSession
                    elif capability.capa_code == capability.CISCO_MULTISESSION_BGP:
                        self.capa_dict['ciscoMultiSession'] = True

                    else:
                        self.capa_dict[str(capability.capa_code)] = capability.capa_value

                    capabilities = capabilities[2 + capability.capa_length:]

                # Go to next Optional Parameter
                self.opt_paras = self.opt_paras[opt_para_length + 2:]

            return {
                'Version': self.version,
                'ASN': self.asn,
                'holdTime': self.hold_time,
                'bgpID': self.bgp_id,
                'Capabilities': self.capa_dict
            }

    @staticmethod
    def construct_header(msg):

        """Prepends the mandatory header to a constructed BGP message
        # 16-octet     2-octet  1-octet
        #---------------+--------+---------+------+
        #    Maker      | Length |  Type   |  msg |
        #---------------+--------+---------+------+
        """
        return struct.pack('!16sHB',
                           chr(255) * 16,
                           len(msg) + 19,
                           1) + msg

    def construct(self, my_capability):

        """ Construct a BGP Open message """
        capas = ''
        # Construct Capabilities Optional Parameter (Parameter Type 2)
        if 'AFI_SAFI' in my_capability:
            # Multiprotocol extentions capability
            capas += Capability(capa_code=1, capa_length=4).construct(my_capability)

        if my_capability['ciscoRouteRefresh']:
            # Cisco Route refresh capability
            capas += Capability(capa_code=128, capa_length=0).construct(my_capability)
        if my_capability['routeRefresh']:
            # Route Refresh capability
            capas += Capability(capa_code=2, capa_length=0).construct(my_capability)

        # 4 bytes ASN
        if self.asn > 65535:
            capas += Capability(capa_code=65, capa_length=4, capa_value=self.asn).construct(my_capability)
            self.asn = 23456
        else:
            if my_capability['4byteAS']:
                capas += Capability(capa_code=65, capa_length=4, capa_value=self.asn).construct(my_capability)

        open_header = struct.pack('!BHHIB', self.version, self.asn, self.hold_time,
                                  self.bgp_id, len(capas))
        message = open_header + capas
        return self.construct_header(message)


# ========================================================================== Optional Parameters

class Capability(object):
    """
       The parameter contains one or more triples <Capability Code,
       Capability Length, Capability Value>, where each triple is encoded as
       shown below:

              +------------------------------+
              | Capability Code (1 octet)    |
              +------------------------------+
              | Capability Length (1 octet)  |
              +------------------------------+
              | Capability Value (variable)  |
              ~                              ~
              +------------------------------+

       The use and meaning of these fields are as follows:

          Capability Code:

             Capability Code is a one-octet unsigned binary integer that
             unambiguously identifies individual capabilities.

          Capability Length:

             Capability Length is a one-octet unsigned binary integer that
             contains the length of the Capability Value field in octets.

          Capability Value:

             Capability Value is a variable-length field that is interpreted
             according to the value of the Capability Code field.
    """

    # Capability Codes (IANA)
    # ---------------------------------------------------------------+
    #   Range  |   Registration Procedures  |          Notes        |
    #   1-63   |       IETF Review          |                       |
    #  64-127  |  First Come First Served   |                       |
    #  128-255 |   Reserved for Private Use |  IANA does not assign |
    # ---------------------------------------------------------------+

    # ---------------------------------------------------------------------------------------------------------------+
    #    Value  |                       Description                      |              Reference                   |
    #      0    |                        Reserved                        |              [RFC5492]                   |
    #      1    |           Multiprotocol Extensions for BGP-4           |              [RFC2858]                   |
    #      2    |           Route Refresh Capability for BGP-4           |              [RFC2918]                   |
    #      3    |           Outbound Route Filtering Capability          |              [RFC5291]                   |
    #      4    |       Multiple routes to a destination capability      |              [RFC3107]                   |
    #      5    |                 Extended Next Hop Encoding             |              [RFC5549]                   |
    #     6-63  |                        Unassigned                      |                                          |
    #      64   |                Graceful Restart Capability             |              [RFC4724]                   |
    #      65   |         Support for 4-octet AS number capability       |              [RFC4893]                   |
    #      66   |                   Deprecated (2003-03-06)              |                                          |
    #      67   |   Support for Dynamic Capability (capability specific) |     [draft-ietf-idr-dynamic-cap]         |
    #      68   |                 Multisession BGP Capability            |          [Chandra_Appanna]               |
    #      69   |                    ADD-PATH Capability                 |       [draft-ietf-idr-add-paths]         |
    #      70   |             Enhanced Route Refresh Capability          | [draft-keyur-bgp-enhanced-route-refresh] |
    #   71-127  |                       Unassigned                       |                                          |
    #   128-255 |                 Reserved for Private Use               |              [RFC5492]                   |
    # ---------------------------------------------------------------------------------------------------------------+

    # =================================================================== Capabilities
    # http://www.iana.org/assignments/capability-codes/

    RESERVED = 0x00  # [RFC5492]
    MULTIPROTOCOL_EXTENSIONS = 0x01  # [RFC2858]
    ROUTE_REFRESH = 0x02  # [RFC2918]
    OUTBOUND_ROUTE_FILTERING = 0x03  # [RFC5291]
    MULTIPLE_ROUTES = 0x04  # [RFC3107]
    EXTENDED_NEXT_HOP = 0x05  # [RFC5549]
    # 6-63      Unassigned
    GRACEFUL_RESTART = 0x40  # [RFC4724]
    FOUR_BYTES_ASN = 0x41  # [RFC4893]
    # 66 Deprecated
    DYNAMIC_CAPABILITY = 0x43  # [Chen]
    MULTISESSION_BGP = 0x44  # [Appanna]
    ADD_PATH = 0x45  # [draft-ietf-idr-add-paths]
    # 70-127    Unassigned
    CISCO_ROUTE_REFRESH = 0x80  # I Can only find reference to this in the router logs
    # 128-255   Reserved for Private Use [RFC5492]

    CISCO_MULTISESSION_BGP = 0x83  # [Multisession BGP draft-ietf-idr-bgp-multisession-06]

    unassigned = range(70, 128)
    reserved = range(128, 256)

    def __init__(self, capa_code=None, capa_length=None, capa_value=None):

        """
          +------------------------------+
          | Capability Code (1 octet)    |
          +------------------------------+
          | Capability Length (1 octet)  |
          +------------------------------+
          | Capability Value (variable)  |
          ~                              ~
          +------------------------------+
        """
        self.capa_code = capa_code
        self.capa_length = capa_length
        self.capa_value = capa_value

    def parse(self, message):

        """
        Partition Capabilities message one by one
        """
        try:
            self.capa_code, self.capa_length = struct.unpack('!BB', message[:2])
        except:
            raise excp.OpenMessageError(
                sub_error=bgp_cons.ERR_MSG_HDR_BAD_MSG_LEN,
                data=message[:2])
        self.capa_value = message[2:self.capa_length + 2]

    def construct(self, my_capability):

        """ Construct a capability PDU """

        # for 4 bytes as
        if self.capa_code == self.FOUR_BYTES_ASN:
            return struct.pack('!BBBBI', 2, 6, self.FOUR_BYTES_ASN, self.capa_length, self.capa_value)

        # for route refresh
        if self.capa_code == self.ROUTE_REFRESH:
            return struct.pack('!BBBB', 2, 2, self.ROUTE_REFRESH, 0)

        # for cisco route refresh
        if self.capa_code == self.CISCO_ROUTE_REFRESH:
            return struct.pack('!BBBB', 2, 2, self.CISCO_ROUTE_REFRESH, 0)

        # graceful restart
        if self.capa_code == self.GRACEFUL_RESTART:
            return struct.pack('!BBBB', 2, 2, self.GRACEFUL_RESTART, 0)

        # for multiprotocol extentions
        if self.capa_code == self.MULTIPROTOCOL_EXTENSIONS:
            # <ipv4,unicast> and <ipv4,mplsvpn>
            afisafi = ''
            for (afi, safi) in my_capability['AFI_SAFI']:
                afisafi += struct.pack('!BBBBHBB', 2, 6, self.MULTIPROTOCOL_EXTENSIONS, 4, afi, 0, safi)
            return afisafi
