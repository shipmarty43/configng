// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "common.hpp"

namespace lw {
// A persistent inode, provisioned by systemd-tmpfiles. Local Linux flock works
// on a read-only descriptor, so the desktop and service need no shared writable file.
struct RadioLock {
    Fd fd;
    explicit RadioLock(const char* path="/run/lock/opi-radio.lock")
        : fd(open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK)) {
        struct stat st{};
        require(fstat(fd.n, &st) == 0 && S_ISREG(st.st_mode) && st.st_nlink == 1,
                "Invalid SX1262 lock file");
        require(flock(fd.n, LOCK_EX | LOCK_NB) == 0, "SX1262 busy or unavailable; inspect lslocks");
    }
};
}
