{pkgs}: {
  deps = [
    pkgs.libgbm
    pkgs.glib
    pkgs.dbus
    pkgs.mesa
    pkgs.xorg.libXrandr
    pkgs.xorg.libXfixes
    pkgs.xorg.libXext
    pkgs.xorg.libXdamage
    pkgs.xorg.libXcomposite
    pkgs.xorg.libxcb
    pkgs.cairo
    pkgs.pango
    pkgs.libxkbcommon
    pkgs.expat
    pkgs.libdrm
    pkgs.cups
    pkgs.at-spi2-atk
    pkgs.atk
    pkgs.alsa-lib
    pkgs.nss
    pkgs.nspr
  ];
}
