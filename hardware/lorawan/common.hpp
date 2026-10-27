// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <openssl/sha.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <algorithm>
#include <array>
#include <cerrno>
#include <charconv>
#include <cstdint>
#include <cstring>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace lw {
inline constexpr const char* revision = "3b1d917bbacba0062dd7064c1157893ef9c6384e";
using Bytes = std::vector<uint8_t>;
inline void require(bool ok, const std::string& message) {
    if (!ok) throw std::runtime_error(message);
}
struct Fd {
    int n;
    explicit Fd(int value) : n(value) { require(n >= 0, "Cannot open required file/device"); }
    ~Fd() { close(n); }
    Fd(const Fd&) = delete;
    Fd& operator=(const Fd&) = delete;
};
inline std::string hex(const Bytes& data) {
    const char* digits = "0123456789abcdef";
    std::string out;
    for (auto b : data) { out += digits[b >> 4]; out += digits[b & 15]; }
    return out;
}
inline Bytes unhex(const std::string& s) {
    require(s.size() % 2 == 0, "Invalid hex length");
    Bytes out;
    auto digit = [](char c) -> unsigned {
        if (c >= '0' && c <= '9') return c - '0';
        if (c >= 'a' && c <= 'f') return c - 'a' + 10;
        if (c >= 'A' && c <= 'F') return c - 'A' + 10;
        throw std::runtime_error("Invalid hex character");
    };
    for (size_t i = 0; i < s.size(); i += 2) out.push_back((digit(s[i]) << 4) | digit(s[i+1]));
    return out;
}
inline std::string digest(const std::string& s) {
    Bytes d(SHA256_DIGEST_LENGTH);
    SHA256(reinterpret_cast<const unsigned char*>(s.data()), s.size(), d.data());
    return hex(d);
}
inline uint64_t number(const std::string& s, uint64_t low, uint64_t high) {
    uint64_t n = 0;
    auto [p, ec] = std::from_chars(s.data(), s.data()+s.size(), n);
    require(ec == std::errc() && p == s.data()+s.size() && n >= low && n <= high,
            "Invalid numeric setting");
    return n;
}
inline std::string readFd(int fd) {
    std::string out;
    char buf[4096];
    ssize_t n;
    while ((n = read(fd, buf, sizeof buf)) != 0) {
        if (n < 0 && errno == EINTR) continue;
        require(n > 0, "File read failed");
        out.append(buf, n);
        require(out.size() <= 65536, "File too large");
    }
    return out;
}
inline void privateFile(int fd) {
    struct stat st{};
    require(fstat(fd, &st) == 0 && S_ISREG(st.st_mode) && st.st_uid == geteuid() &&
            (st.st_mode & 077) == 0 && st.st_nlink == 1,
            "Sensitive file must be owned by this user, regular, unlinked elsewhere and mode 0600");
}
inline std::map<std::string,std::string> fields(const std::string& text) {
    std::map<std::string,std::string> out;
    std::istringstream in(text);
    std::string line;
    while (std::getline(in, line)) {
        if (line.empty() || line[0] == '#') continue;
        auto p = line.find('=');
        require(p != std::string::npos && p > 0 && p+1 < line.size(), "Expected key=value");
        require(out.emplace(line.substr(0,p), line.substr(p+1)).second, "Duplicate setting");
    }
    return out;
}
struct Config {
    bool enabled = false, verified = false, confirmed = false;
    std::string spi, identity;
    uint64_t joinEui = 0, devEui = 0;
    Bytes appKey, payload;
    unsigned interval = 300, port = 10;
    static Config parse(const std::string& config, const std::string& credentials) {
        auto f = fields(config), k = fields(credentials);
        const std::vector<std::string> allowed = {"schema","enabled","wiring_verified","region",
            "class","activation","spidev","interval_seconds","fport","confirmed","payload_hex"};
        for (const auto& [name,value] : f)
            require(std::find(allowed.begin(), allowed.end(), name) != allowed.end(), "Unknown configuration key");
        require(f.size() == allowed.size(), "Missing configuration key");
        require(k.size() == 3 && k.count("join_eui") && k.count("dev_eui") && k.count("app_key"), "Expected join_eui, dev_eui, app_key only");
        require(f.at("schema") == "1" && f.at("region") == "EU433" && f.at("class") == "A" &&
                f.at("activation") == "OTAA-1.0.4", "Supported profile: schema 1, EU433, Class A, OTAA-1.0.4");
        auto flag = [](const std::string& v) { require(v == "true" || v == "false", "Expected true/false"); return v == "true"; };
        Config c;
        c.enabled = flag(f.at("enabled")); c.verified = flag(f.at("wiring_verified"));
        c.confirmed = flag(f.at("confirmed"));
        c.spi = f.at("spidev");
        require(c.spi.starts_with("/dev/spidev"), "Expected explicit /dev/spidevBUS.CS");
        auto suffix = c.spi.substr(11); auto dot = suffix.find('.');
        require(dot != std::string::npos, "Invalid spidev path");
        number(suffix.substr(0,dot),0,255); number(suffix.substr(dot+1),0,255);
        c.interval = number(f.at("interval_seconds"),300,86400);
        c.port = number(f.at("fport"),1,223);
        c.payload = unhex(f.at("payload_hex"));
        require(!c.payload.empty() && c.payload.size() <= 32, "Payload must contain 1..32 bytes");
        auto eui = [](const std::string& s) {
            require(s.size() == 16, "EUI must contain 16 hex digits, MSB first");
            uint64_t value = 0;
            for (auto b : unhex(s)) value = (value << 8) | b;
            return value;
        };
        c.joinEui = eui(k.at("join_eui")); c.devEui = eui(k.at("dev_eui"));
        c.appKey = unhex(k.at("app_key"));
        require(c.devEui != 0 && c.appKey.size() == 16 &&
                std::any_of(c.appKey.begin(),c.appKey.end(),[](auto b){return b != 0;}), "Invalid device identity/key");
        c.identity = digest(std::string(revision)+"/EU433/OTAA-1.0.4/"+
                            std::to_string(c.joinEui)+"/"+std::to_string(c.devEui)+"/"+hex(c.appKey));
        return c;
    }
};
inline Config loadConfig(const std::string& path, const std::string& keys) {
    Fd f(open(path.c_str(),O_RDONLY|O_CLOEXEC|O_NOFOLLOW));
    Fd k(open(keys.c_str(),O_RDONLY|O_CLOEXEC|O_NOFOLLOW));
    privateFile(f.n); privateFile(k.n);
    return Config::parse(readFd(f.n),readFd(k.n));
}
struct Snapshot {
    std::string identity;
    Bytes nonces, session;
    uint64_t readyAt = 0;
    std::string encode() const {
        std::string body = "OPILW1\n"+identity+"\n"+hex(nonces)+"\n"+
                           (session.empty()?"-":hex(session))+"\n"+std::to_string(readyAt)+"\n";
        return body+digest(body)+"\n";
    }
    static Snapshot decode(const std::string& data, const std::string& identity) {
        std::istringstream in(data); std::vector<std::string> v; std::string s;
        while (std::getline(in,s)) v.push_back(s);
        require(v.size()==6 && v[0]=="OPILW1" && v[1]==identity, "State version/identity mismatch; do not reset counters");
        Snapshot out{v[1],unhex(v[2]),v[3]=="-"?Bytes{}:unhex(v[3]),number(v[4],0,UINT64_MAX)};
        require(out.encode() == data, "State corrupt; restore trustworthy state or provision a new identity");
        return out;
    }
};
// Directory and lock outlive all updates. Never fall back to blank state on errors.
class Store {
    Fd dir, lock;
public:
    explicit Store(const std::string& path) : dir(open(path.c_str(),O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW)),
        lock(openat(dir.n,"state.lock",O_CREAT|O_RDWR|O_CLOEXEC|O_NOFOLLOW,0600)) {
        struct stat st{};
        require(fstat(dir.n,&st)==0 && st.st_uid==geteuid() && (st.st_mode&077)==0,
                "State directory must be owned by this user and mode 0700");
        privateFile(lock.n);
        require(flock(lock.n,LOCK_EX|LOCK_NB)==0,"State is owned by another process");
    }
    bool exists() const {
        struct stat st{};
        if(fstatat(dir.n,"state",&st,AT_SYMLINK_NOFOLLOW)==0) return true;
        require(errno==ENOENT,"Cannot inspect state"); return false;
    }
    Snapshot load(const std::string& identity) const {
        Fd f(openat(dir.n,"state",O_RDONLY|O_CLOEXEC|O_NOFOLLOW)); privateFile(f.n);
        return Snapshot::decode(readFd(f.n),identity);
    }
    void save(const Snapshot& snapshot) const {
        std::string name = ".state."+std::to_string(getpid());
        // An interrupted previous process may leave a temporary file. Never reuse it.
        static unsigned counter = 0; name += "."+std::to_string(++counter);
        Fd f(openat(dir.n,name.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600));
        try {
            auto data=snapshot.encode(); size_t done=0;
            while(done<data.size()) {
                auto n=write(f.n,data.data()+done,data.size()-done);
                if(n<0 && errno==EINTR) continue;
                require(n>0,"State write failed"); done+=n;
            }
            require(fsync(f.n)==0,"State fsync failed");
            require(renameat(dir.n,name.c_str(),dir.n,"state")==0,"State rename failed");
            require(fsync(dir.n)==0,"State directory fsync failed");
        } catch(...) { unlinkat(dir.n,name.c_str(),0); throw; }
    }
};
}
