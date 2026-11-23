# Alternativas de licencia para NetTerm

NetTerm es una reimplementación independiente a partir de la **lista pública de
funciones** de MobaXterm. No contiene código, binarios ni recursos de MobaXterm
(su núcleo es Cygwin + OpenSSH + PuTTY, todos open source por separado).

La elección de licencia depende de dos cosas:

1. **¿Cuánto quieres que otros reutilicen tu código?** (permisividad)
2. **¿Quieres que las mejoras te vuelvan?** (copyleft)

| Licencia | Tipo | Uso comercial | Copyleft | Patentes | Compatibilidad con GPL |
|---|---|---|---|---|---|
| **MIT** | Permisiva | Sí | No | No explícito | Sí |
| **BSD-3-Clause** | Permisiva | Sí | No | No explícito | Sí |
| **Apache-2.0** | Permisiva | Sí | No | **Sí** (grant explícito) | Sí (no compatible con GPLv2) |
| **ISC** | Permisiva | Sí | No | No | Sí |
| **MPL-2.0** | Copyleft débil (por archivo) | Sí | Sí, solo en los ficheros modificados | No | Sí |
| **LGPL-3.0** | Copyleft débil (enlazado) | Sí | Sí, en las bibliotecas | No | Sí |
| **GPL-3.0** | Copyleft fuerte | Sí | **Todo** el programa | No | — |
| **AGPL-3.0** | Copyleft fuerte + red | Sí | Todo, **incluido el uso por red** | No | — |
| **Unlicense** / Dominio público | Permisiva | Sí | No | No | No (es una donation) |

---

## Recomendación por escenario

### 1. MIT — *la más simple y la que más se usa*

```text
Copyright (c) 2026 NetTerm contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, ... (texto completo)
```

- ✅ 4 líneas de licencia, imposible equivocarse
- ✅ Todo el mundo puede usarlo, incluso en software propietario
- ✅ Sin condición de copyleft: nadie te obliga a compartir
- ✅ Contributors: cada persona conserva la autoría de sus líneas
- ❌ Sin protección de patentes
- ❌ No obliga a nadie a devolver las mejoras

### 2. Apache-2.0 — *permisiva + Grado de patentes*

- ✅ Como MIT en cuanto a permisividad
- ✅ **Cláusula de patentes**: whoever lo use no puede demandarte por patentes
  que se apliquen a tu trabajo. Es la que usan Google, Microsoft, Android…
- ✅ Acepta contribuciones con claridad sobre la licencia de las无心ías
- ❌ 11 KB de texto legal
- ❌ No es compatible con GPLv2 (sí con GPLv3)
- ⚠️ Obligatoria la cabecera NOTICE en los ficheros modificados

### 3. MPL-2.0 — *copyleft por archivo*

- ✅ Puedes usar NetTerm dentro de un programa propietario
- ✅ Solo los ficheros que tú modifiques deben publicarse con MPL
- ✅ Compromiso razonable
- ❌ Más complejo de entender que un copyleft simple

### 4. GPL-3.0 — *copyleft fuerte* (el actual)

- ✅ Si alguien distribuye NetTerm (o un programa derivado) debe publicar
  el código fuente completo bajo GPL
- ✅ Obliga a que las mejoras regresen al proyecto
- ✅ Es la licencia de la mayoría del software libre de Linux (GNOME, KDE)
- ✅ Compatible con Apache-2.0 (a diferencia de GPLv2)
- ❌ No se puede integrar en software propietario
- ❌ Puede scares a empresas

### 5. AGPL-3.0 — *copyleft fuerte + uso por red*

- ✅ Como GPL-3.0, pero **también** si alguien ofrece NetTerm como servicio
  por red (SaaS) debe publicar el código
- ✅ Cubre el caso moderno de "lo ejecuto en mi servidor y te cobro"
- ✅ La que usa Nextcloud, Grafana, Mattermost
- ❌ Máxima fricción para adopción corporativa

---

## Recomendación para este proyecto

**Si el objetivo es que NetTerm se use mucho → MIT o Apache-2.0.**
**Si el objetivo es que las mejoras vuelvan al proyecto → GPL-3.0.**

Para un clon de una herramienta propietario, la opción que mejor encaja es
**GPL-3.0** (la actual): protege a quien contribuya y encaja con el ecosistema
GNOME/KDE, donde se van a comparar las dos herramientas. Si prefieres máxima
adopción sin condiciones, **Apache-2.0** es la mejor elección moderna: es
permisiva e incluye la cláusula de patentes.

---

## Cómo cambiar de licencia

Es un cambio de una línea en cuatro sitios:

```bash
cd ~/netterm

# 1. El fichero de licencia
cp LICENSE MIT            # o Apache-2.0, BSD-3-Clause…

# 2. La cabecera del README
#    (cambiar la sección "## Licencia")

# 3. El spec del RPM
sed -i 's/^License:.*/License:        MIT/' packaging/netterm.spec

# 4. Reconstruir y volver a etiquetar
./packaging/build-rpm.sh
git add -A && git commit -m "Cambia la licencia a MIT"
```

> ⚠️ **Importante**: cambiar la licencia de un proyecto ya publicado es
> problemático. Solo es lícito cambiar la licencia del código **propio**; el
> código de terceros que se haya incorporado con otra licencia mantiene la
> suya. Si el proyecto ya tiene historial público, lo más limpio es publicar
> la nueva versión bajo la licencia elegida y dejar la anterior intacta.

---

## Nota sobre la relación con MobaXterm

- MobaXterm es software **propietario** de MobaXterm/BMob; su EULA prohíbe la
  ingeniería inversa.
- NetTerm se ha escrito **desde cero** en Python/GTK4, sin descompilar ni
  copiar código de MobaXterm. Solo se ha usado su **lista pública de
  funciones** como especificación, que no es protegible por derechos de autor.
- Los componentes que MobaXterm empaqueta (OpenSSH, PuTTY, Cygwin, PuTTYgen)
  tienen sus propias licencias, en general permisivas, y aquí se usan los
  originales de cada distribución Linux.
- MobaXterm permite uso comercial de la edición Professional, pero eso no
  afecta a la licencia del código propio de NetTerm.

Si en algún momento se quisiera distribuir un producto comercial basado en
NetTerm, la ruta segura es: mantener NetTerm bajo una licencia copyleft
fuerte y modular los componentes propietarios, o bien usar una licencia
permisiva y firmar Contributor License Agreements con los colaboradores.
