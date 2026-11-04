# 多身份浏览器（macOS / Windows）

一个轻量级的多身份方案：每个身份使用独立 Profile，因此 Cookie、LocalStorage、IndexedDB、历史记录、扩展、下载目录和代理配置互不共享。默认浏览器是 Firefox；同一个身份也可以改用 Chrome、Edge、Brave 或 Chromium，仍然只用本机已经安装的那一份浏览器。

每个身份的地区特征（IP、时区、语言、地理位置）由 `identities/*.conf` 声明。Firefox 把它们写进 Profile，不依赖扩展。Chromium 系能固定的项目少一些，见下文「浏览器」。

macOS 与 Windows 共用同一份 Python 实现（`mif/` 包），`bin/` 下只是薄封装。

## 初始化

前提：已安装 Python 3，以及身份配置里用到的浏览器。仓库自带的身份用 Firefox。

macOS：

```bash
cd multi-identity-firefox
chmod +x bin/mif bin/*.sh
./bin/setup.sh
```

Windows：

```bat
cd multi-identity-firefox
bin\setup.cmd
```

会在 `apps/` 下为每个身份生成启动器，macOS 是 `.app`，Windows 是 `.lnk`：

```text
apps/
├── Firefox - Normal.app        (Windows: Firefox - Normal.lnk)
├── Firefox - US-West.app
├── Firefox - JP-Tokyo.app
└── Firefox - Temporary.app
```

`./bin/install.sh`（Windows 用 `bin\install.cmd`）会把它们复制到常用位置：macOS 是 `~/Applications/Browser Identities`，Windows 是桌面和开始菜单。

随时可以用 `./bin/status.sh` 查看每个身份实际生效的时区、代理和坐标。

## 身份配置

配置位于 `identities/*.conf`，两个平台共用同一份，可以跟着 git 在机器间同步：

```bash
NAME="US-West"
BROWSER="firefox"
LANGUAGE="en-US"
LOCALE="en-US"
TIMEZONE="America/Los_Angeles"
PROXY_TYPE="socks5"
PROXY_HOST="127.0.0.1"
PROXY_PORT="1080"
GEO_LAT="34.0522"
GEO_LON="-118.2437"
FINGERPRINT_PROTECTION="true"
TEMPORARY="false"
```

支持 `none`、`http`、`socks5` 三种代理。代理只作用于该身份，不修改系统全局网络设置。Firefox 写进 Profile；Chromium 系用启动参数，并且不继承系统代理。

修改配置后重新运行 `setup` 即可。Firefox 的 `user.js` 在每次启动时都会被重新生成，所以在 `about:config` 或设置界面里改动这些被管理的 pref 不会保留，要改就改 conf 文件。Chromium 系在每次冷启动时把受管理的 Preferences 合并回去；浏览器正在运行时不会写，否则它退出时会用内存里的旧内容覆盖。

`data/` 和 `apps/` 是本机产物，不进 git，两台机器各自生成。

## 浏览器

`BROWSER` 选择这个身份启动哪一个浏览器，省略时是 `firefox`。可选值：

- `firefox`
- `chrome`
- `edge`
- `brave`
- `chromium`

可执行文件按平台查找，也可以用环境变量指定。变量名是 `MIF_CHROME_BIN` 这种形式。Firefox 同时接受原来的 `FIREFOX_BIN` 和 `MIF_FIREFOX_BIN`。

改了 `BROWSER` 之后重新运行 `setup`。启动器名字会跟着变，例如 `Chrome - JP-Tokyo.app`。已经复制到桌面上的旧快捷方式需要自己删掉。`~/Applications/Browser Identities` 和 Windows 开始菜单里的同名目录会在 `install` 时清掉过期项。

各浏览器能固定的东西不一样：

- **Firefox**：时区、语言、坐标、代理、指纹保护都写进该 Profile。
- **Chrome、Edge、Chromium**：
  - 时区在 macOS 上通过 `TZ` 生效。Windows 上这些浏览器不读 `TZ`（ICU 在 Win32 上走系统时区，不看环境变量），`setup` 会拒绝生成启动器，除非该身份写了 `TIMEZONE_FALLBACK="host"`。
  - `navigator.languages` 跟随 `LANGUAGE`。Windows 和 Linux 上界面语言跟随 `LOCALE`（`--lang`）。macOS 上界面语言和 `Intl` 的默认 locale 仍是系统语言：把 `-AppleLanguages` 按两个参数传进去时，Chrome 会把它当成第二个要打开的地址；`--lang` 则被忽略。
  - 代理用启动参数，不继承系统代理。`PROXY_TYPE="none"` 是直连。代理挂掉不会改走直连。
  - 配了 `GEO_LAT` / `GEO_LON` 时不能把坐标写死，改为默认拒绝定位权限。页面拿不到位置，也就拿不到机器的真实位置。没配则不干预。
  - 没有 Firefox 那种指纹保护开关。`FINGERPRINT_PROTECTION="true"` 不会生效，`setup` 会提示。
- **Brave**：和上面相同。另外 Brave Shields 默认开启，本身会扰动指纹。`FINGERPRINT_PROTECTION` 不是 Shields 的开关。

Profile 目录：Firefox 仍是 `data/<身份>/profile`，已有数据不用迁移。其他浏览器是 `data/<身份>/profile-<浏览器>`。

## 时区

启动器在拉起浏览器前设置 `TZ`。Firefox，以及 macOS 上的 Chromium 系，都通过 ICU 读取它，网页看到的 `Intl` 和 `Date` 时区就是这个值。不需要扩展。

macOS 上任意 IANA 时区都可用，实测：

```text
timeZone : Asia/Tokyo
offset   : 9h
```

### Windows 的限制

下面这张白名单只约束 Firefox。Chromium 系在 Windows 上完全不读 `TZ`，见「浏览器」。

Windows 上 Firefox 的 `TZ` 要先过 SpiderMonkey 的 `IsOlsonCompatibleWindowsTimeZoneId()`（`js/src/vm/DateTime.cpp`），那是一张硬编码白名单：

```text
EST5EDT  CST6CDT  MST7MDT  PST8PDT
GMT+0  GMT-0  GMT0  UCT  UTC  GMT
```

`Asia/Tokyo` 这类 IANA 名称会被**静默拒绝**，Firefox 转而使用宿主机时区。所以本项目在 Windows 上做两件事：

一是自动映射夏令时规则确实与美国一致的时区：

```text
America/Los_Angeles, America/Vancouver, America/Tijuana  ->  PST8PDT
America/Denver, America/Edmonton                          ->  MST7MDT
America/Chicago, America/Winnipeg                         ->  CST6CDT
America/New_York, America/Toronto                         ->  EST5EDT
UTC, Etc/UTC, Etc/GMT, GMT                                ->  UTC
```

`America/Phoenix` 一类不实行夏令时的区**故意不映射**，套用 `MST7MDT` 会让它半年内偏移一小时。

二是对映射不了的时区（如 `Asia/Tokyo`、`Asia/Shanghai`），`setup` 直接拒绝生成该身份的启动器并说明原因。GUI 启动看不到控制台输出，所以把关卡放在 `setup` 阶段，避免出现"以为伪装成功、实际暴露宿主时区"的情况。

确实可以接受用宿主时区时，在该身份的 conf 里显式写：

```bash
TIMEZONE_FALLBACK="host"
```

如果那台 Windows 本来就在目标时区（比如宿主在上海、身份也是 `Asia/Shanghai`），这样做没有任何损失。

## 地理位置

坐标通过 Firefox 原生 pref 固定，由 `GEO_LAT` / `GEO_LON` 生成。Firefox 会优先使用平台定位服务，全部关掉之后才会走 `geo.provider.network.url`，所以三个平台的开关都写上，不适用的会被忽略：

```javascript
user_pref("geo.provider.testing", true);
user_pref("geo.provider.network.url", "data:application/json,{...}");
user_pref("geo.provider.use_corelocation", false);   // macOS
user_pref("geo.provider.ms-windows-location", false); // Windows
user_pref("geo.provider.use_geoclue", false);         // Linux
```

用 `data:` URL 承载坐标是因为 Mozilla Location Service 已于 2024 年关停，网络定位后端不再可用。

Chromium 系没有对应的 pref。配了坐标的身份会把定位权限默认设为拒绝，见「浏览器」。

实测确认页面拿到的就是配置值，不是机器真实位置：配置 `12.3456 / 65.4321`，页面 `getCurrentPosition` 返回 `lat=12.3456 lon=65.4321`。

留空 `GEO_LAT` / `GEO_LON` 则不干预 Geolocation API。

## IP / 公网地址

固定坐标不会改变公网 IP。要让网站看到不同国家/城市的公网地址，仍然需要独立代理/VPN 出口：

```bash
PROXY_TYPE="socks5"
PROXY_HOST="127.0.0.1"
PROXY_PORT="1080"
```

SOCKS5 模式下 DNS 通过 `network.proxy.socks_remote_dns` 交给代理远端解析。

代理不支持用户名密码：Firefox 的 pref 装不下凭据。需要认证的上游代理请在本地起一层中继（如 gost），再把本项目指向本地端口。

## 防泄漏

代理生效时，真实 IP 主要通过三条路径泄漏，生成的 `user.js` 都做了处理：

- **代理故障回落**。Firefox 默认 `network.proxy.failover_direct = true`，代理挂掉时会静默改走直连。这里强制为 `false`，代理不可用就直接失败。
- **WebRTC**。`media.peerconnection.ice.proxy_only = true` 强制 ICE 只走代理，`default_address_only` 限制候选地址枚举。
- **预解析**。`network.dns.disablePrefetch` 和 `network.predictor.enabled` 关掉在正常请求路径之外发生的名称解析。

## 指纹保护

这一节只适用于 Firefox。Chrome、Edge、Chromium 没有等价开关；Brave 靠 Shields 的默认行为，见「浏览器」。

不使用 `privacy.resistFingerprinting`：它会把网页可见时区强制成 UTC，与身份的地区设定冲突。

改用 Firefox 128 起提供的细粒度开关，精确排除掉会破坏时区和语言的两个 target：

```javascript
user_pref("privacy.fingerprintingProtection", true);
user_pref("privacy.fingerprintingProtection.overrides", "+AllTargets,-JSDateTimeUTC,-JSLocale");
```

实测对比（同为 JP-Tokyo 配置）：

```text
                     FINGERPRINT_PROTECTION=true   FINGERPRINT_PROTECTION=false
timeZone             Asia/Tokyo                    Asia/Tokyo
language             ja-JP                         ja-JP
hardwareConcurrency  8                             10   (M4 真实核心数)
canvas 指纹          每次会话变化                   固定
```

时区和语言不受影响，canvas 和硬件信息则被保护。个别站点若因此渲染异常，可在该身份的 conf 里设 `FINGERPRINT_PROTECTION="false"`。

## Cookie 与追踪

Firefox 当前 Standard 模式已经包含 Total Cookie Protection，它为网站提供隔离的 Cookie Jar，减少第三方跨站 Cookie 追踪。本方案另外为每个身份使用独立 Firefox Profile，因此不同身份之间的 Cookie / Storage 也完全分离。

## 平台差异

下表是 Firefox 在两个系统上的差别。换浏览器见「浏览器」。

| | macOS | Windows |
| --- | --- | --- |
| Firefox 定位 | `/Applications/Firefox.app` | 注册表 `PathToExe`，回落到 Program Files |
| 启动器 | `.app` bundle | `.lnk` 快捷方式，指向 `pythonw -m mif launch` |
| 多实例参数 | `-no-remote -new-instance` | `-no-remote`（`-new-instance` 是 Unix 专有） |
| 时区 | 任意 IANA | 白名单映射，详见上文 |
| 窗口分组 | Dock | `taskbar.grouping.useprofile` 让任务栏按 Profile 分组 |

两个平台都可以用 `FIREFOX_BIN` 或 `MIF_FIREFOX_BIN` 指定 Firefox。其他浏览器用 `MIF_<浏览器>_BIN`，例如 `MIF_CHROME_BIN`。

### Apple Silicon

`/Applications/Firefox.app` 是 universal binary。从脚本启动会落到 x86_64 切片、整个浏览器跑在 Rosetta 下。启动器会检测 arm64 主机并用 `arch -arm64` 强制原生启动。

## Temporary

`Temporary` 身份设置了：

```bash
TEMPORARY="true"
```

关闭浏览器不会自动删除数据。需要清空时：

```bash
./bin/wipe.sh Temporary
```

下次启动会重新创建空 Profile。

## 验证

`./bin/status.sh` 列出每个身份的实际生效状态，包括 Windows 上时区是否被映射或拒绝。

在浏览器里打开开发者控制台执行：

```javascript
Intl.DateTimeFormat().resolvedOptions().timeZone
navigator.language
navigator.languages
navigator.geolocation.getCurrentPosition(console.log)
```

也可以不开窗口，直接截图检查：

```bash
./bin/launch.sh JP-Tokyo --headless "--screenshot=/tmp/check.png" https://example.com
```

Chromium 系可以用 headless 把页面里的时区和语言打出来：

```bash
./bin/launch.sh SomeChromeIdentity --headless=new --dump-dom file:///tmp/check.html
```

IP 出口和 WebRTC 泄漏则通过 IP 检测服务确认。

## 从旧版本升级

早期版本依赖 **Spoof Timezone** 和 **Spoof Geolocation** 两个扩展，现已全部由原生 pref 取代。这两个扩展应当卸载：它们通过注入 JS 覆盖 `Date` 和 `Intl`，留下可被检测的 hook 痕迹，且与原生 pref 叠加后行为不确定。装有这两个扩展的 Profile 在 headless 模式下无法完成启动（同配置的干净 Profile 正常），交互模式未测试。

在 `about:addons` 里移除，或直接清空该身份的 Profile 重建。

早期版本的 `bin/common.sh` 和 `bin/create-apps.sh` 已被 `mif/` 包取代，`bin/` 下的脚本行为保持不变。

## 身份设计原则

每个身份应保持长期、稳定、一致的组合，例如：

```text
US-West
├── IP          = 美国西海岸代理出口
├── Language    = en-US
├── Timezone    = America/Los_Angeles
├── Geolocation = Los Angeles
└── Profile     = 固定
```

这里的目标是"身份隔离"和"地区一致性"，而不是每次随机改变浏览器指纹。

## 边界

本方案不提供 VM/容器级的安全隔离：所有 Profile 以同一个用户身份运行，彼此的文件在操作系统层面可读。如果需要"一个身份被攻破不影响其他身份"，需要每身份独立系统账户或独立虚拟机。
