"""Test doubles for ADB.

The sample texts follow the format printed by a Samsung SM-A600F running
Android 10, trimmed to the parts the code reads. The serial number is invented
and the operator is replaced by the international test network 001-01. The
"<MASKED>" values are as Android printed them.
"""

from __future__ import annotations

from collections.abc import Sequence

from cellsurvey.receivers.adb import AdbClient

SERIAL = "5200abcdef123456"

DEVICES_NONE = "List of devices attached\n\n"
DEVICES_READY = (
    "List of devices attached\n"
    f"{SERIAL}       device usb:1-3 product:a6ltejx model:SM_A600F device:a6lte transport_id:7\n"
    "\n"
)
DEVICES_UNAUTHORIZED = (
    f"List of devices attached\n{SERIAL}       unauthorized usb:1-2 transport_id:1\n\n"
)

GETPROP = """\
[gsm.network.type]: [HSPAP,Unknown]
[gsm.operator.alpha]: [Test Network]
[gsm.operator.numeric]: [00101]
[gsm.sim.state]: [LOADED,ABSENT]
[ro.build.version.release]: [10]
[ro.build.version.sdk]: [29]
[ro.product.manufacturer]: [samsung]
[ro.product.model]: [SM-A600F]
"""

_CELL_IDENTITY = (
    "CellIdentityWcdma:{ mLac=<MASKED> mCid=<MASKED> mPsc=122 mUarfcn=10712 "
    "mMcc=001 mMnc=01 mAlphaLong=Test Network mAlphaShort=Test}"
)
_NO_SIGNAL = (
    "SignalStrength:{mCdma=Invalid,mGsm=Invalid,mWcdma=Invalid,mTdscdma=Invalid,mLte=Invalid,"
    "mNr=Invalid,SignalBarInfo{ no level },P,rat=14,primary=CellSignalStrengthLte}"
)

# Slot 0 holds a SIM registered on UMTS; slot 1 is empty.
REGISTRY_SLOT_0 = f"""\
  Phone Id=0
    mCallState=0
    mServiceState={{mVoiceRegState=0(IN_SERVICE), mDataRegState=0(IN_SERVICE), \
mChannelNumber=10712, getRilVoiceRadioTechnology=3(UMTS), getRilDataRadioTechnology=15(HSPAP), \
mNetworkRegistrationInfos=[NetworkRegistrationInfo{{ domain=CS transportType=WWAN \
registrationState=HOME accessNetworkTechnology=UMTS cellIdentity={_CELL_IDENTITY}}}]}}
    mSignalStrength=SignalStrength:{{mCdma=Invalid,mGsm=Invalid,mWcdma=CellSignalStrengthWcdma: \
ss=-87 ber=99 rscp=-79 ecno=0 level=3,mTdscdma=Invalid,mLte=Invalid,mNr=Invalid,\
SignalBarInfo{{ wcdmaLevel=4 }},P,rat=3,primary=CellSignalStrengthWcdma}}
    mCellLocation=Bundle[mParcelledData.dataSize=64]
    mCellInfo=[CellInfoWcdma:{{mRegistered=YES mTimeStamp=17374344423421ns \
mCellConnectionStatus=0 {_CELL_IDENTITY} CellSignalStrengthWcdma: ss=-83 ber=0 \
rscp=2147483647 ecno=2147483647 level=3}}]
"""
REGISTRY_SLOT_1 = f"""\
  Phone Id=1
    mCallState=0
    mServiceState={{mVoiceRegState=1(OUT_OF_SERVICE), mDataRegState=1(OUT_OF_SERVICE), \
mChannelNumber=0, getRilVoiceRadioTechnology=0(Unknown), mNetworkRegistrationInfos=[]}}
    mSignalStrength={_NO_SIGNAL}
    mCellLocation=Bundle[{{cid=-1, lac=-1, psc=-1}}]
    mCellInfo=null
"""
REGISTRY = "last known state:\n" + REGISTRY_SLOT_0 + REGISTRY_SLOT_1

SHELL_OUTPUTS = {"getprop": GETPROP, "dumpsys telephony.registry": REGISTRY}


class FakeAdb(AdbClient):
    """An ``AdbClient`` that answers from canned text instead of running adb."""

    def __init__(
        self,
        devices_output: str = DEVICES_NONE,
        shell_outputs: dict[str, str] | None = None,
        error: Exception | None = None,
    ) -> None:
        super().__init__()
        self.devices_output = devices_output
        self.shell_outputs = dict(SHELL_OUTPUTS if shell_outputs is None else shell_outputs)
        self.error = error
        self.calls: list[tuple[str | None, tuple[str, ...]]] = []

    def run(self, args: Sequence[str], serial: str | None = None) -> str:
        self.calls.append((serial, tuple(args)))
        if self.error is not None:
            raise self.error
        if list(args) == ["devices", "-l"]:
            return self.devices_output
        assert args[0] == "shell", f"unexpected adb command: {args}"
        return self.shell_outputs[args[1]]

    def shell_calls(self) -> list[str]:
        """Shell commands issued so far."""
        return [args[1] for _, args in self.calls if args[0] == "shell"]
