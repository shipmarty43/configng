/* Fixture for the pinned Linux backend. All ioctl requests are handled locally
 * or rejected. Nothing is forwarded to the kernel. The two /dev mounts must
 * be regular files in a private network and device namespace. */
#include <errno.h>
#include <fcntl.h>
#include <gpiod.h>
#include <linux/spi/spidev.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <unistd.h>

static const char *spi_file, *gpio_file;
static struct stat spi;
static uint32_t expected_speed, current_speed;
static uint8_t registers[65536], packet_type;
static _Atomic int levels[288];
static atomic_bool irq_observed;

static void reject(const char *why) {
    fprintf(stderr, "MOCK REJECT %s\n", why);
    _exit(78);
}

__attribute__((constructor))
static void init_model(void) {
    struct stat gpio;
    const char *speed = getenv("OPI_FIXTURE_HZ");
    expected_speed = speed ? (uint32_t)strtoul(speed,NULL,10) : 2000000;
    if (!expected_speed || expected_speed > 2000000) reject("fixture speed");
    spi_file = getenv("OPI_FIXTURE_SPI");
    gpio_file = getenv("OPI_FIXTURE_GPIO");
    if (!spi_file || !gpio_file || lstat(spi_file, &spi) || !S_ISREG(spi.st_mode)
        || lstat(gpio_file, &gpio) || !S_ISREG(gpio.st_mode))
        reject("expected two ordinary files");
    /* RadioLib uses the SX1261 family version string for the SX1262. */
    memcpy(registers + 0x320, "SX1261", 6);
}

struct gpiod_chip *gpiod_chip_open(const char *path) {
    if (strcmp(path, gpio_file)) reject("unexpected GPIO controller");
    return (struct gpiod_chip *)&spi;
}
void gpiod_chip_close(struct gpiod_chip *chip) { (void)chip; }

struct gpiod_line_request *gpiod_chip_request_lines(struct gpiod_chip *chip,
        struct gpiod_request_config *consumer, struct gpiod_line_config *config) {
    unsigned int offsets[2];
    (void)consumer;
    if (chip != (struct gpiod_chip *)&spi || gpiod_line_config_get_configured_offsets(config, offsets, 2) != 1)
        reject("unexpected GPIO request");
    unsigned int n = offsets[0];
    if (n != 76 && n != 257 && n != 260 && n != 271) reject("unexpected GPIO offset");
    fprintf(stderr, "MOCK GPIO %u\n", n);
    return (struct gpiod_line_request *)&levels[n];
}
void gpiod_line_request_release(struct gpiod_line_request *line) { (void)line; }

int gpiod_line_request_reconfigure_lines(struct gpiod_line_request *line, struct gpiod_line_config *config) {
    (void)line; (void)config;
    return 0;
}
enum gpiod_line_value gpiod_line_request_get_value(struct gpiod_line_request *line, unsigned int n) {
    if (n >= 288 || line != (struct gpiod_line_request *)&levels[n]) reject("GPIO read");
    if (n == 76 && (access("mock-irq", F_OK) == 0 || access("mock-good", F_OK) == 0)) {
        if (!atomic_exchange(&irq_observed, 1)) fprintf(stderr, "MOCK DIO1 HIGH\n");
        return GPIOD_LINE_VALUE_ACTIVE;
    }
    return levels[n] ? GPIOD_LINE_VALUE_ACTIVE : GPIOD_LINE_VALUE_INACTIVE;
}
int gpiod_line_request_set_value(struct gpiod_line_request *line, unsigned int n, enum gpiod_line_value value) {
    if ((n != 257 && n != 271) || line != (struct gpiod_line_request *)&levels[n]) reject("GPIO write");
    levels[n] = value == GPIOD_LINE_VALUE_ACTIVE;
    fprintf(stderr, "MOCK LEVEL %u %d\n", n, levels[n]);
    return 0;
}

int ioctl(int fd, unsigned long request, ...) {
    struct stat file;
    if (fstat(fd, &file) < 0) return -1;
    if (S_ISSOCK(file.st_mode) && request == FIONBIO) {
        va_list socket_args;
        va_start(socket_args, request);
        int nonblock = *va_arg(socket_args, int *);
        va_end(socket_args);
        int flags = fcntl(fd,F_GETFL);
        if (flags < 0) return -1;
        return fcntl(fd,F_SETFL, nonblock ? flags | O_NONBLOCK : flags & ~O_NONBLOCK);
    }
    if (!S_ISREG(file.st_mode) || file.st_dev != spi.st_dev || file.st_ino != spi.st_ino) {
        errno = ENOTTY;
        return -1;
    }
    va_list args;
    va_start(args, request);
    void *arg = va_arg(args, void *);
    va_end(args);
    if (request == SPI_IOC_WR_MODE32 && *(uint32_t *)arg == 0) return 0;
    if (request == SPI_IOC_RD_MODE32) { *(uint32_t *)arg = 0; return 0; }
    if (request == SPI_IOC_RD_LSB_FIRST) { *(uint8_t *)arg = 0; return 0; }
    if (request == SPI_IOC_WR_BITS_PER_WORD && *(uint8_t *)arg == 8) return 0;
    if (request == SPI_IOC_RD_BITS_PER_WORD) { *(uint8_t *)arg = 8; return 0; }
    if (request == SPI_IOC_RD_MAX_SPEED_HZ) { *(uint32_t *)arg = current_speed; return 0; }
    if (request == SPI_IOC_WR_MODE || request == SPI_IOC_WR_LSB_FIRST) {
        if (*(uint8_t *)arg != 0) reject("SPI mode/order");
        return 0;
    }
    if (request == SPI_IOC_WR_MAX_SPEED_HZ) {
        current_speed = *(uint32_t *)arg;
        /* Portduino restores its idle default outside each transfer. */
        if (current_speed != expected_speed && current_speed != 2000000) reject("SPI clock");
        return 0;
    }
    if (request != SPI_IOC_MESSAGE(1)) reject("unexpected SPI ioctl");
    struct spi_ioc_transfer *x = arg;
    const uint8_t *tx = (const uint8_t *)(uintptr_t)x->tx_buf;
    uint8_t *rx = (uint8_t *)(uintptr_t)x->rx_buf;
    size_t size = x->len;
    if (!tx || !rx || tx == rx || !size || size > 512 || x->cs_change) reject("SPI framing");
    if ((x->speed_hz ? x->speed_hz : current_speed) != expected_speed) reject("transaction clock");
    if (x->bits_per_word && x->bits_per_word != 8) reject("word length");
    uint8_t op = tx[0];
    memset(rx, 0, size);
    if (size > 1) rx[1] = 0x22;
    if (op == 0x83 || op == 0xd1 || op == 0xd2) reject("TX command");
    if (op == 0x97) reject("TCXO command on crystal board");
    if (op == 0x1d || op == 0x0d) {
        size_t skip = op == 0x1d ? 4 : 3;
        if (size < skip) reject("short register frame");
        unsigned int reg = ((unsigned int)tx[1] << 8) | tx[2];
        if (size - skip > sizeof(registers) - reg) reject("register range");
        if (op == 0x1d) memcpy(rx + skip, registers + reg, size - skip);
        else memcpy(registers + reg, tx + skip, size - skip);
    } else if (op == 0x8a && size == 2) {
        packet_type = tx[1];
    } else if (op == 0x11 && size == 3) {
        rx[2] = packet_type;
    } else if (op == 0xc0 && size >= 3) {
        rx[2] = 0x22;
    } else if (op == 0x12 && size == 4 && access("mock-irq", F_OK) == 0) {
        rx[3] = 0x42; /* RX_DONE and CRC_ERR; the synthetic frame must be discarded. */
        fprintf(stderr, "MOCK IRQ STATUS\n");
    } else if (op == 0x12 && size == 4 && access("mock-good", F_OK) == 0) {
        rx[3] = 0x02;
    } else if (op == 0x14 && size == 5 && access("mock-good", F_OK) == 0) {
        rx[2] = 207; rx[3] = 0xe3; rx[4] = 80;
    } else if (op == 0x1e && size == 6 && access("mock-good", F_OK) == 0) {
        rx[3] = 0x10; rx[4] = 'A'; rx[5] = 'B';
    } else if (op == 0x13 && size == 4) {
        rx[2] = access("mock-good", F_OK) == 0 ? 3 : 20; /* Synthetic received length. */
    } else if (op == 0x02 && size == 3 && (tx[2] & 2) && unlink("mock-irq") == 0) {
        fprintf(stderr, "MOCK IRQ CLEAR\n");
    } else if (op == 0x02 && size == 3 && (tx[2] & 2) && unlink("mock-good") == 0) {
        fprintf(stderr, "MOCK GOOD IRQ CLEAR\n");
    } else if (op == 0x9d && size == 2 && tx[1] == 1) {
        fprintf(stderr, "MOCK DIO2 SWITCH\n");
    } else if (op == 0x86 && size == 5) {
        uint32_t word = (uint32_t)tx[1] << 24 | (uint32_t)tx[2] << 16 | (uint32_t)tx[3] << 8 | tx[4];
        fprintf(stderr, "MOCK RF HZ %.0f\n", (double)word * 32000000 / 33554432);
    } else if (op == 0x82) {
        if (!levels[271]) reject("RX without RF switch");
        fprintf(stderr, "MOCK RX\n");
    }
    return (int)size;
}

/* Additional v2 queries used by python3-libgpiod. Each request is one line. */
struct gpiod_chip_info *gpiod_chip_get_info(struct gpiod_chip *chip) {
    return (struct gpiod_chip_info *)chip;
}
void gpiod_chip_info_free(struct gpiod_chip_info *info) { (void)info; }
const char *gpiod_chip_info_get_name(struct gpiod_chip_info *info) { (void)info; return "gpio-fixture"; }
const char *gpiod_chip_info_get_label(struct gpiod_chip_info *info) { (void)info; return "main-pio-fixture"; }
size_t gpiod_chip_info_get_num_lines(struct gpiod_chip_info *info) { (void)info; return 288; }
const char *gpiod_line_request_get_chip_name(struct gpiod_line_request *r) { (void)r; return "gpio-fixture"; }
size_t gpiod_line_request_get_num_requested_lines(struct gpiod_line_request *r) { (void)r; return 1; }
size_t gpiod_line_request_get_requested_offsets(struct gpiod_line_request *r, unsigned int *out, size_t count) {
    if (!count) return 0;
    *out = (unsigned int)((_Atomic int *)r - levels);
    return 1;
}
int gpiod_line_request_get_values_subset(struct gpiod_line_request *r, size_t count,
                                        const unsigned int *offsets, enum gpiod_line_value *values) {
    for (size_t i=0; i<count; ++i) values[i]=gpiod_line_request_get_value(r,offsets[i]);
    return 0;
}
int gpiod_line_request_set_values_subset(struct gpiod_line_request *r, size_t count,
                                        const unsigned int *offsets, const enum gpiod_line_value *values) {
    for (size_t i=0; i<count; ++i) gpiod_line_request_set_value(r,offsets[i],values[i]);
    return 0;
}
