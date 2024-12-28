# Precision Trigger

There are two things that a clock needs; an accurate rate (ie that time counts forward),
and an accurate synchronization method.

For this project we are intending that it will be (eventually) clocked from the GPSDO, 
but for now we are relying on the Pico's XTAL. On my other project I have replaced the 
stock XTAL with a TCXO, which works much better.

Since the 'time' is held within the PIO State Machines (they just count forward according 
to their clock rate), we need a way to precisely start them at the correct time - from the
1PPS signal.

We can use a `wait()` instruction, and even `irq()` to signal other State Machines, but 
this has a fundimental flaw... the accuracy of the sync is limited to the clock rate of
the State Machine. The edge is registered **after** it has occured, at the next clock,
so will be 'lagging' (randomly by *up-to* 83us with a 12KHz clock).

## Trigger Scheme

In order to improve the trigger we use an intermediate State Machine, running at a higher
rate. In fact we use two:

* SM-0: 12MHZ (SysClock / 10) - Once triggered, counts some time before trigger CPU IRQ and 
counts some more.
* SM-1: 120MHz (SysClock) - Detects 1PPS edge and triggers SM-0

The IRQ is triggered part way throught the count so that the CPU is given enough time to 
enter the Interrupt Service Routine before the count completes. The moment it completes is
precisely 1 period **after** the 1PPS trigger, and this is the moment we start the final
(slow) State Machine which will be used to track the time.

![Precision Trigger Scope Plot](https://github.com/mungewell/pico-irig/blob/main/docs/pics/precision_trigger_for_low_rate_clock_SM.png)

After the final State Machine is started SM-0 and SM-1 can be stopped, as SM-4 (??) will 
continue to run autonomously.

## The ISR

The State Machines do not have a way to start another, they can only use `wait` or `irq(block)`
which are timing dependant on the clock rate. The ISR code runs at SysClock rate and is the
most precise way to start a State Machine (that has previsely been loaded).

We need to 'bridge' the CPU clock and State Machine clock(s) ensuring that the CPU is exactely
aligned. We do this by monitoring the instruction counter for the SM-0 State Machine.

Since this is clocked at 12MHz (SysClock / 10), and we need a few instructions to read the SM
instruction counter, we end up with 5 possible flows (or offsets between the two clock 
domains). Using some cycle precise code we can re-read the instruction counter with slighly 
different timing to compute which of these flows is happening, and then we can align the
CPU clock with the SM clock....

![CPU code flows](https://github.com/mungewell/pico-irig/blob/main/docs/pics/even_more_flows.png)

In the diagram above:

* black boarders show actual code, this is same as used in 'other flows'.
* grey fill show branch instructions which are NOT 'taken', these take 1 CPU cycle. When 'taken'
  the instruction takes 2 cycles, and helps us compensate for timing difference between flows.
* the various green shows instruction counter value when read, and also on the bar on the left.

So by comparing the read value, we can delay (or not) slightly, and after all this the flows are
aligned to the SM-0 clock.

Once aligned, we can confidently enable the final State Machine(s) at **precisely** the correct
time. Well almost... 

# The icing on the cake

SM-0 is clocked at 'SysClock / 10' and can be (randomly) *up-to* 83ns delayed. So we use 
another trick; once SM-0 is triggered, it asserts a GPIO and this is 'read back' into SM-1.

The flow of SM-1 is halted when this GPIO is asserted, and this effectively 'stores' the
clock relationship between the 120MHz SM-1 and 12MHz SM-2. I call this 'phase'.

The 'phase' is held in one-of-ten instruction counter 'addresses', and is held until the 
GPIO is de-asserted - at which point SM-1 will continue, loop and be ready to trigger again.

So the ISR **also** reads the 'phase', and uses this to insert additional delay (up-to 10
CPU cycles).

**Now we are PRECISELY starting the final State Machine** (albeit 1 cycle **after** the trigger).

After these tricks we can measure the delay between trigger and final State Machine, for a
larger number of successive runs we compute statistics:

```
$ cat precision2.dat 
     11 0.000083322
     51 0.000083324
     42 0.000083326
     48 0.000083328
     46 0.000083330
     71 0.000083332
     73 0.000083334
     72 0.000083336
     63 0.000083338
     23 0.000083340
```

Precision is ~ +/-10ns.

Since the 1PPS trigger is **Asynchronous**, a tiny/immeasurable change can mean that it is
not seen until the next cycle - hence a 8.3ns delta. *I am not sure why there is a sub-cycle
difference, maybe something to do with double-clocked input and/or slight differences in the
CPU clock?*
