### Runtime CPU power settings

Select a policy, then choose an available governor or a maximum frequency.
Policies may cover multiple cores. Frequency choices come from the kernel;
the minimum frequency and thermal protection are preserved. Changes take effect
immediately, are read back to verify them, and are not persisted across reboot.
Another power manager may subsequently override them.

The menu does not change CPU voltages, charging settings, or device-tree OPPs.
The `userspace` governor is omitted from the menu because it requires a separate
target-frequency control. When a driver has no frequency table, governor
selection remains available. The CLI also accepts maximum frequencies within
the driver's bounds; kernel rounding is reported as a read-back mismatch.

```sh
armbian-config --cmd CPUP01
armbian-config --api module_cpu_power status
armbian-config --api module_cpu_power governor policy0 schedutil
armbian-config --api module_cpu_power max policy0 1008000
```

The last two commands are examples: choose a policy, governor and frequency
actually supported by your board. Frequency values use kHz. Read-only discovery
does not require writes; applying changes requires OS permission for CPUFreq.
The module never loads drivers or installs a persistent service automatically.

The upstream role-tuning profiles remain separate: they also change memory and
filesystem settings. A CPU power choice here only changes the selected CPUFreq
attribute. See [Linux CPUFreq documentation](https://docs.kernel.org/admin-guide/pm/cpufreq.html).

Development validation: Bats tests use temporary sysfs fixtures and fake dialogs;
they do not change the host's CPU policy. Physical Orange Pi Zero 2W validation
is still pending. Run `bats tests/bats/cpu_power.bats` from the source checkout.
