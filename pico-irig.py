import rp2
import utime
from machine import Pin, disable_irq, enable_irq, mem32, freq, I2C

from micropython import alloc_emergency_exception_buf
alloc_emergency_exception_buf(100)

# https://github.com/pangopi/micropython-DS3231-AT24C32
from libs.ds3231 import DS3231

# Clock speeds
irig_freq = 12000		# For IRIG-B
#irig_freq = 120000		# For IRIG-A
ext_freq = 10000000     # ie when 1PPS is 1 period of 10MHz
cpu_freq = 120000000

# Trigger source
IRIG_FAKE = 0
IRIG_RTC = 1
IRIG_GPS = 2
irig_trigger = IRIG_FAKE

IRIG_PPS_RISING = 0
IRIG_PPS_FALLING = 1
irig_polarity = IRIG_PPS_FALLING

# globals
irig_sm = []
irig_fifo = []
irig_seconds = 0.0

sync_ticks_us = 0
pps_ticks_us = 0

fail = 0
core_dis = [0, 0]


'''
Basis is that High/Low cycles will be formed with the hack for
different output levels from (ab)using the internal Pull-Up/-Downs.

External resistors set the relative amplitude of the low cycle.

High Cycle:
    set(pindirs, 0b11) .side(0b01) [1]		# Zero = Low, High
    set(pindirs, 0b11) .side(0b11) [3]		# High = High, High
    set(pindirs, 0b11) .side(0b01) [1]		# Zero = Low, High
    set(pindirs, 0b11) .side(0b00) [3]		# Low  = Low, Low

Low Cycle:
    set(pindirs, 0b11) .side(0b01) [1]		# Zero = Low, High
    set(pindirs, 0b01) .side(0b01) [3]		# high = In-pull Low, High
    set(pindirs, 0b11) .side(0b01) [1]		# Zero = Low, High
    set(pindirs, 0b10) .side(0b00) [3]		# low  = Low, In-Pull High


Each cycle takes 12 PIO clocks, and we'll reduce the 'nop()'s to
allow for other required instructions/op-codes

The 'requested cycle' is passed via the FIFO with 2bits per bit, these
are 'extracted' by a separate/synchronized SM and placed on pins:
    0b00 - Data '0'
    0b01 - Data '1'
    0b10 - Pr, P1..P9, P0
'''


@rp2.asm_pio(autopull=True,
             fifo_join=rp2.PIO.JOIN_TX, out_shiftdir=rp2.PIO.SHIFT_RIGHT)

def setup():
    #irq(clear, rel(0))
    irq(4)
    out(null, 32)
    out(null, 32)
    out(null, 32)
    out(null, 32)
    out(null, 32)
    out(null, 32)
    out(null, 32)
    out(null, 32)


@rp2.asm_pio()

def start_from_pin_rising():
    wait(0, pin, 0)
    wait(1, pin, 0)

    irq(clear, 4)					# Trigger Sync
    #irq(rel(0))					# set IRQ for ticks_us monitoring


@rp2.asm_pio()

def start_from_pin_falling():
    wait(1, pin, 0)
    wait(0, pin, 0)

    irq(clear, 4)					# Trigger Sync
    #irq(rel(0))					# set IRQ for ticks_us monitoring


@rp2.asm_pio(out_init=[rp2.PIO.OUT_LOW] * 2, autopull=True,
             fifo_join=rp2.PIO.JOIN_TX, out_shiftdir=rp2.PIO.SHIFT_RIGHT)

def irig_fifo():
    set(x, 11-2)					# FIFO holds 11x Pr/P1..0, which we count out
    out(pins, 2)					# Preload first bit-pair for better timing
    jmp(not_osre, "pre-load-done")
    jmp("fail")
 
    label("pre-load-done")
    irq(block, 4)					# Wait for Sync'ed start
 
    label("start-of-frame")
    irq(rel(0))                     # set IRQ for ticks_us monitoring
    label("loop")
    set(y, 23-1)					# delay = (12 clocks * 10 cycles) - 5
    label("delay")
    jmp(y_dec, "delay") [4]
 
    out(pins, 2)					# output next bit-pair
    jmp(not_osre, "continue")
 
    label("fail")					# UNDERFLOW - when Python fails to fill FIFOs
    irq(rel(0))                     # set IRQ to warn other StateMachines
    wrap_target()
    set(pins, 0)
    wrap()
 
    label("continue")
    jmp(pin, "px_frame")			# check HIGH=Pr/P1..0, and count them...
    jmp("loop")
    label("px_frame")
    jmp(x_dec, "loop")

    nop() [30]						# padding to (12 clocks * 10 cycles) - 7
    nop() [30]
    out(null, 24) [30]				# clear out unused-bits section of ISR
    set(x, 11-2) [23]				# FIFO holds 11x Pr/P1..0
    out(pins, 2)					# output first bit-pair of frame
    jmp(not_osre, "start-of-frame")
    jmp("fail")


@rp2.asm_pio(out_init=[rp2.PIO.OUT_HIGH])

def irig_dcls():
    wrap_target()
    mov(pins, pins)
    wrap()


@rp2.asm_pio(set_init=[rp2.PIO.OUT_HIGH])

def irig_enc():
    set(x, 3)
    set(y, 2)
 
    irq(block, 4) [2]  						# Wait for Sync'ed start
    wrap()									# abuse wrap for PPS sync

    label("start-of-symbol")				# loop for 2 x 12 clocks
    set(pins, 1)
    in_(pins, 2)
    mov(y, isr)
 
    wrap_target()
    label("high_cycle_pt2")
    jmp(x_dec, "high_cycle_pt2") [4]
    jmp(not_y, "low_cycle")
 
    set(x, 5) [3]							# add another 3 x 12 clocks
    jmp(y_dec, "high_cycle_pt2")

    label("low_cycle")
    set(pins, 0)
 
    jmp(pin, "low_cycle_continue") [19]		# for 'Pr/Px, 2 * 12 clocks = 24
    mov(y, isr)
    set(x, 16) [1]							# for 'Data 0', 8 * 12 clocks = 96
    jmp(not_y, "low_cycle_pt2")   
    set(x, 6) [3]							# for 'Data 1', 5 * 12 clocks = 60

    label("low_cycle_pt2")
    jmp(x_dec, "low_cycle_pt2") [3]

    label("low_cycle_continue")
    in_(null, 32)							# clear ISR
    set(x, 3)
    jmp("start-of-symbol")


@rp2.asm_pio(sideset_init=[rp2.PIO.IN_HIGH, rp2.PIO.IN_LOW],
         set_init=[rp2.PIO.IN_HIGH, rp2.PIO.IN_LOW])

def irig_ask():
    irq(block, 4) [1]						# Wait for Sync'ed start
 
    # fall through for faster PPS sync

    label("high_cycle")
    set(pindirs, 0b11) .side(0b11) [3]		# High = High, High
    set(pindirs, 0b11) .side(0b01) [1]		# Zero = Low, High
    set(pindirs, 0b11) .side(0b00) [3]		# Low  = Low, Low

    wrap_target()
    label("start-of-cycle")
    set(pindirs, 0b11) .side(0b01)			# Zero = Low, High
    jmp(pin, "high_cycle")
    set(pindirs, 0b01) .side(0b01) [3]		# high = In-pull Low, High
    set(pindirs, 0b11) .side(0b01) [1]		# Zero = Low, High
    set(pindirs, 0b10) .side(0b00) [3]		# low  = Low, In-Pull High
    #jmp("start-of-cycle")    
    wrap()

  
# ---

@micropython.asm_thumb
def sync_sm(r0, r1):
    mov(r2, 0xf)
    mov(r3, 8)
    lsl(r2, r3)
    str(r2, [r0, 0])
    str(r2, [r1, 0])


def irq_handler(m):
    global core_dis, stop, irig_sm, fifo
    global sync_ticks_us, pps_ticks_us

    core_dis[mem32[0xd0000000]] = disable_irq()
    ticks = utime.ticks_us()

    if m==irig_sm[1]:
        # reset the clock-phases with CLKDIV_RESTART
        mem32[0x50300000] = 0x00000f00		# Block-2 first as more critical
        mem32[0x50200000] = 0x00000f00
 
        sync_ticks_us = ticks

    if m==irig_sm[3]:
        pps_ticks_us = ticks

    if m==irig_sm[fifo]:
        # Buffer Underflow
        fail = 1

    enable_irq(core_dis[mem32[0xd0000000]])


# -----
packed = []
p_phase = 0

def pack(value, count=1, pr = False):
    # Pack pairs into array words ready for FIFOs, low bits first
    global irig_fifo, p_phase
 
    while count:
        if p_phase == 0:
            irig_fifo.append(0)
 
        if not pr:
            irig_fifo[len(irig_fifo)-1] |= (value & 0x01) << (p_phase * 2)
        else:
            irig_fifo[len(irig_fifo)-1] |= 0x02 << (p_phase * 2)
 
        value = value >> 1
        p_phase = (p_phase + 1) & 0x0f	# 16 pairs per 32bit FIFO word
        count -= 1


def pack_clear():
    global irig_fifo, p_phase

    irig_fifo = []
    p_phase = 0


def pack_test(value=0xAA):
    # Pack a frame with a test pattern
    pack_clear()
    pack(0, 1, True)				# Pr
    pack(value, 8)
    for i in range(8):
        pack(0, 1, True)			# P1..8
        pack(0xAA, 9)
    pack(0, 1, True)				# Pr9
    pack(0xCC, 9)
    pack(0, 1, True)				# Pr0


def pack_from_seconds(abs_sec = 0.0):
    # Pack a frame using float 'seconds'
    gm = utime.gmtime(int(abs_sec))
 
    midnight = utime.mktime([gm[0], gm[1], gm[2], \
                0, 0, 0, gm[6], gm[7]])

    # Encoding definition from:
    # https://en.wikipedia.org/wiki/IRIG_timecode
    pack_clear()
    pack(0, 1, True)				# Pr
    pack(gm[5] % 10, 4)			    # Seconds
    pack(0, 1)
    pack(int(gm[5] / 10), 3)

    pack(0, 1, True)				# P1
    pack(gm[4] % 10, 4)			    # Minutes
    pack(0, 1)
    pack(int(gm[4] / 10), 4)

    pack(0, 1, True)				# P2
    pack(gm[3] % 10, 4)			    # Hours
    pack(0, 1)
    pack(int(gm[3] / 10), 4)

    pack(0, 1, True)				# P3
    pack(gm[7], 4)				    # Day of Year
    pack(0, 1)
    pack(gm[7] >> 4, 4)

    pack(0, 1, True)				# P4
    pack(gm[7] >> 8, 2)			    # Day of Year, continued
    pack(0, 3)
    pack(int((abs_sec-int(abs_sec))*10), 4) # Tenths of second

    pack(0, 1, True)				# P5
    pack(gm[0] % 10, 4)			    # Year (00-99)
    pack(0, 1)
    pack(int(gm[0] / 10) % 10, 4)

    # Definitions from:
    # https://en.wikipedia.org/wiki/IEEE_1344
    pack(0, 1, True)				# P6
    pack(0, 9)                      # forcing 'UTC' with no leap seconds
    pack(0, 1, True)				# P7
    pack(0, 1)                      # no 0.5 TZ
    if irig_trigger == IRIG_FAKE:
        pack(0xF, 4)                # quality is 'not-reliable'
    else:
        pack(0, 4)                  # quality is 'no particular accuracy'

    p = 0                           # compute parity
    for i in range(len(irig_fifo)):
        for j in range(16):
            if (irig_fifo[i] >> ((j+1)*2)) & 1:
                p += 1              # ie Pr, P1..9, P0
            else:
                p += (irig_fifo[i] >> (j*2)) & 1
    pack((p & 1), 1)
    pack(0, 3)

    pack(0, 1, True)				# P8
    pack(int(abs_sec-midnight), 9)
    pack(0, 1, True)				# P9
    pack(int(abs_sec-midnight) >> 9, 9)
    pack(0, 1, True)				# P0


#---------------------------------------------

if __name__ == "__main__":
    # Ensure the CPU frequency is optimal
    # ie. does not cause fraction div on StateMachine clocks
    if freq() != cpu_freq:
        freq(cpu_freq)
 
    # preset ASK pins as inputs, with pull resitors set up/down
    Pin(0, Pin.IN, Pin.PULL_UP)
    Pin(1, Pin.IN, Pin.PULL_DOWN)

    # configure the PPS pin
    pps = machine.Pin(18, machine.Pin.IN, machine.Pin.PULL_UP)
 
    # setup the StateMachines, ensuring FIFO is empty and IRQ set
    irig_sm = []
    irig_sm.append(rp2.StateMachine(0, setup, freq=ext_freq))
    irig_sm.append(rp2.StateMachine(1, setup, freq=ext_freq))
    irig_sm.append(rp2.StateMachine(2, setup, freq=ext_freq))
    irig_sm.append(rp2.StateMachine(3, setup, freq=ext_freq))
    irig_sm.append(rp2.StateMachine(4, setup, freq=ext_freq))
    irig_sm.append(rp2.StateMachine(5, setup, freq=ext_freq))
    irig_sm.append(rp2.StateMachine(6, setup, freq=ext_freq))
    irig_sm.append(rp2.StateMachine(7, setup, freq=ext_freq))
    for m in range(len(irig_sm)):
        irig_sm[m].active(1)
    utime.sleep(0.5)
    rp2.PIO(0).remove_program()
    rp2.PIO(1).remove_program()
 
    # On PIO Block-1
    irig_sm = []
    if irig_polarity == IRIG_PPS_RISING:
        irig_sm.append(rp2.StateMachine(0, start_from_pin_rising, freq=ext_freq, \
                            in_base=Pin(18), jmp_pin=Pin(18)))
        irig_sm.append(rp2.StateMachine(1, start_from_pin_rising, freq=cpu_freq, \
                            in_base=Pin(18), jmp_pin=Pin(18)))
    else:
        irig_sm.append(rp2.StateMachine(0, start_from_pin_falling, freq=ext_freq, \
                            in_base=Pin(18), jmp_pin=Pin(18)))
        irig_sm.append(rp2.StateMachine(1, start_from_pin_falling, freq=cpu_freq, \
                            in_base=Pin(18), jmp_pin=Pin(18)))
    fifo_sm = len(irig_sm)
    irig_sm.append(rp2.StateMachine(2, irig_fifo, freq=irig_freq, \
                        out_base=Pin(3), jmp_pin=Pin(4)))
    irig_sm.append(rp2.StateMachine(3, irig_dcls, freq=irig_freq, \
                        in_base=Pin(5), out_base=Pin(6)))

    # On PIO Block-2
    if irig_polarity == IRIG_PPS_RISING:
        irig_sm.append(rp2.StateMachine(4, start_from_pin_rising, freq=ext_freq, \
                            in_base=Pin(18), jmp_pin=Pin(18)))
    else:
        irig_sm.append(rp2.StateMachine(4, start_from_pin_falling, freq=ext_freq, \
                            in_base=Pin(18), jmp_pin=Pin(18)))
    irig_sm.append(rp2.StateMachine(5, irig_enc, freq=irig_freq, \
                        set_base=Pin(5), in_base=Pin(3), \
                        jmp_pin=Pin(4)))
    irig_sm.append(rp2.StateMachine(6, irig_ask, freq=irig_freq, \
                        sideset_base=Pin(0), set_base=Pin(0), \
                        jmp_pin=Pin(5)))

    '''
    # set up IRQ handler(s)
    for m in irig_sm:
        m.irq(handler=irq_handler, hard=True)
    '''
    
    # pre-set the IRQ4 on each SM with IRQ_FORCE
    mem32[0x50200034] = 1 << 4
    mem32[0x50300034] = 1 << 4
 
    # re-align the clock-phases with CLKDIV_RESTART
    sync_sm(0x50300000, 0x50200000)          # Block-2 first as more timing critical

    # Pre-start most StateMachines
    mem32[0x50300000] = 0x0000000e
    mem32[0x50200000] = 0x00000004

    # Pre-fill the entry in FIFO
    if irig_sm[fifo_sm].tx_fifo() < 1:
        #pack_test()
        pack_from_seconds(irig_seconds)
        for p in irig_fifo:
            irig_sm[fifo_sm].put(p)
        irig_seconds += (12000 / irig_freq)

    print("State Machines armed, start scope now :-)")
    utime.sleep(5)
 
    # ---
    # Test section: True for fake, False for RTC
    if irig_trigger == IRIG_FAKE:
        # Enable the rest of StateMachines
        mem32[0x50200000] = 0x0000000d
        mem32[0x50300000] = 0x0000000f
 
        utime.sleep(0.2)
 
        # Start the StateMachines asserting (fake) 1PPS low
        pps = machine.Pin(18, machine.Pin.OUT, value=0)
        utime.sleep(0.1)
        pps = machine.Pin(18, machine.Pin.IN, machine.Pin.PULL_UP)
    else:
        # Start the StateMachines using a 1PPS signal
        # (for now using a RTC chip as our 1PPS reference)
        ds = DS3231(I2C(0, sda=Pin(16), scl=Pin(17)))
        ds.square_wave(freq=ds.FREQ_1)

        while pps.value() == 1:
            # wait for PPS to deassert first, as some are 1Hz signals...
            utime.sleep(0.25)
 
        # Enable the rest of StateMachines
        mem32[0x50200000] = 0x0000000f
        mem32[0x50300000] = 0x0000000f
    # ---
 
    # wait for the trigger to have happen
    while mem32[0x50300030]  & (1 << 4):		# Block-2 IRQ4
        utime.sleep(0.1)
 
    # Loop, filling the FIFO as needed
    print("IRIG running...")
    count = 0
    while not fail:
        if irig_sm[fifo_sm].tx_fifo() < 1:
            pack_from_seconds(irig_seconds)
            irig_seconds += (12000 / irig_freq)
            '''
            pack_test(count)
            count = (count + 1) & 0xFF
            '''
            for p in irig_fifo:
                irig_sm[fifo_sm].put(p)
            print(".", end="")
        utime.sleep(0.001)

    print("IRIG complete/aborted")

