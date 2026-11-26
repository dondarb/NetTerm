%global pkgname netterm

Name:           %{pkgname}
Version:        1.2.0
Release:        1%{?dist}
Summary:        Terminal avanzada, alternativa nativa a MobaXterm en Linux

#GPL-3.0-or-later
License:        GPL-3.0-or-later
URL:            https://github.com/netterm/netterm
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch

# Sin python3-devel instalado en este equipo, se calculan las rutas a mano.
%global python3_sitelib %(python3 -c "import sys; print('/usr/lib/python%d.%d/site-packages' % sys.version_info[:2])")
%global python3_bindir /usr/bin

BuildRequires:  python3-devel
BuildRequires:  desktop-file-utils

Requires:       python3 >= 3.9
Requires:       gtk4
Requires:       libadwaita
# Tipografía GI de VTE para GTK4 (Vte-3.91)
Requires:       vte291-gtk4
Requires:       python3-paramiko
Requires:       python3-pyserial
Requires:       python3-cryptography

# Herramientas de red opcionales pero muy útiles
Recommends:     nmap
Recommends:     nmap-ncat
Recommends:     traceroute
Recommends:     mtr
Recommends:     iperf3
Recommends:     mosh
Recommends:     tigervnc-viewer
Recommends:     xfreerdp
Recommends:     openssh-clients

%description
NetTerm es un cliente de terminal, SSH, SFTP y consola serie para Linux,
escrito en Python y GTK4. Es una reimplementación independiente y libre de
las funciones de MobaXterm, sin usar su código ni sus binarios.

A diferencia de las alternativas que corren bajo Wine/Bottles, NetTerm habla
directamente con el sistema:

* Consola serie RS-232 sobre termios, con acceso real a /dev/ttyUSB*.
* Detección dinámica de todas las tarjetas de red, incluidos los dispositivos
  que se conectan en caliente.
* Herramientas de red nativas: ping, barrido de subred, traceroute, mtr,
  nmap y escaneo de puertos TCP/UDP.
* Explorador SFTP gráfico, editor remoto con resaltado de sintaxis.
* Gestión de sesiones, macros, modo multi-ejecución, túneles SSH, servidores
  embebidos y gestor de paquetes.

%prep
%autosetup

%build

%install
# --- Módulo Python -------------------------------------------------------
mkdir -p %{buildroot}%{python3_sitelib}
cp -r netterm %{buildroot}%{python3_sitelib}/netterm
find %{buildroot}%{python3_sitelib}/netterm -name '__pycache__' -type d \
    -exec rm -rf {} + 2>/dev/null || :
find %{buildroot}%{python3_sitelib}/netterm -name '*.pyc' -delete 2>/dev/null || :

# --- Lanzador -------------------------------------------------------------
mkdir -p %{buildroot}%{_bindir}
cat > %{buildroot}%{_bindir}/%{pkgname} <<'EOF'
#!/usr/bin/python3
# Lanzador de NetTerm.
import os
import sys


def main() -> int:
    os.environ.setdefault("PYTHONWARNINGS", "ignore::DeprecationWarning")
    try:
        from netterm.app import main as app_main
    except ImportError:
        sys.stderr.write(
            "No se encuentra el modulo 'netterm'. "
            "Reinstala el paquete: sudo dnf install netterm\n")
        return 1
    return app_main()


if __name__ == "__main__":
    sys.exit(main())
EOF
chmod 0755 %{buildroot}%{_bindir}/%{pkgname}

# --- Entrada de escritorio -------------------------------------------------
mkdir -p %{buildroot}%{_datadir}/applications
sed -e 's|^Exec=.*|Exec=%{_bindir}/%{pkgname}|' \
    -e 's|^Icon=.*|Icon=%{pkgname}|' \
    data/%{pkgname}.desktop > %{buildroot}%{_datadir}/applications/%{pkgname}.desktop
sed -i 's|^Name=.*|Name=NetTerm|' \
    %{buildroot}%{_datadir}/applications/%{pkgname}.desktop

# --- Icono ----------------------------------------------------------------
mkdir -p %{buildroot}%{_datadir}/icons/hicolor/scalable/apps
cp data/%{pkgname}.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/%{pkgname}.svg

# --- Documentación ---------------------------------------------------------
mkdir -p %{buildroot}%{_docdir}/%{pkgname}
cp README.md %{buildroot}%{_docdir}/%{pkgname}/README.md

# Compilación de bytecodes (equivalente a %py_byte_compile, pero sin depender
# del control de procesos del macro en este entorno de construcción).
%{__python3} -m compileall -q %{buildroot}%{python3_sitelib}/netterm

%check
# Comprobación de sintaxis de todos los módulos.
%{__python3} -m compileall -q %{buildroot}%{python3_sitelib}/netterm
# La entrada de escritorio debe ser válida.
desktop-file-validate %{buildroot}%{_datadir}/applications/%{pkgname}.desktop

%files
%license LICENSE
%license NOTICE
%doc %{_docdir}/%{pkgname}
%{_bindir}/%{pkgname}
%{_datadir}/applications/%{pkgname}.desktop
%{_datadir}/icons/hicolor/scalable/apps/%{pkgname}.svg
%{python3_sitelib}/netterm

%post
%update_desktop_database
for icon in %{_datadir}/icons/hicolor/scalable/apps; do
    touch "$icon/.dir-info" 2>/dev/null || :
done
if [ -x %{_bindir}/gtk-update-icon-cache ]; then
    %{_bindir}/gtk-update-icon-cache -q %{_datadir}/icons/hicolor/scalable/apps || :
fi

%postun
%update_desktop_database
if [ -x %{_bindir}/gtk-update-icon-cache ]; then
    %{_bindir}/gtk-update-icon-cache -q %{_datadir}/icons/hicolor/scalable/apps || :
fi

%changelog
* Mon Nov 23 2026 NetTerm <netterm@example.org> - 1.0.0-1
- Primera version: terminal, SSH, SFTP, consola serie y herramientas de red.
