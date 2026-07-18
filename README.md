# NEOCP Explorer — Ephemeris Calculator

**NEOCP Explorer** is a desktop application for calculating ephemerides and orbital information for known near-Earth objects and current NEOCP candidates.

No local Find_Orb installation is required. Ephemerides and preliminary orbital solutions are obtained from the Project Pluto online Find_Orb service. The application uses MPC NEOCP data for the candidate list, Astropy for local topocentric Alt/Az and airmass calculations, and optionally integrates with Cartes du Ciel for telescope slewing via TCP.

---

**NEOCP Explorer** é uma aplicação desktop para calcular efemérides e informações orbitais de objetos próximos da Terra conhecidos e candidatos NEOCP atuais.

Não é necessária nenhuma instalação local do Find_Orb. Efemérides e soluções orbitais preliminares são obtidas do serviço online Find_Orb do Project Pluto. O programa usa dados NEOCP do MPC para a lista de candidatos, Astropy para cálculos topocêntricos locais de Alt/Az e massa de ar, e integra opcionalmente com o Cartes du Ciel para apontamento do telescópio via TCP.

---

## Table of Contents / Índice

- 🇺🇸 [English](#english)
  - [Download](#download)
  - [Main features](#main-features)
  - [Requirements](#requirements)
  - [Running from source](#running-from-source)
  - [Using the application](#using-the-application)
  - [Ephemeris columns](#ephemeris-columns)
  - [Cartes du Ciel integration](#cartes-du-ciel-integration)
  - [Building an executable](#building-an-executable)
  - [Troubleshooting](#troubleshooting)
  - [Data sources and acknowledgements](#data-sources-and-acknowledgements)
  - [Changelog](#changelog)
- 🇧🇷 [Português](#português)
  - [Download](#download-1)
  - [Funcionalidades principais](#funcionalidades-principais)
  - [Requisitos](#requisitos)
  - [Rodando pelo código-fonte](#rodando-pelo-código-fonte)
  - [Usando o programa](#usando-o-programa)
  - [Colunas da efeméride](#colunas-da-efeméride)
  - [Integração com Cartes du Ciel](#integração-com-cartes-du-ciel)
  - [Gerando o executável](#gerando-o-executável)
  - [Solução de problemas](#solução-de-problemas)
  - [Fontes de dados e agradecimentos](#fontes-de-dados-e-agradecimentos)
  - [Histórico de versões](#histórico-de-versões)

---

# English

## Download

Pre-built Windows executables are available on the [Releases page](https://github.com/Anduin-source/NEOCP_Explorer/releases).

No Python installation required. Download the latest release and run `NEOCP_Explorer.exe` directly.

---

## Main features

- Loads the current MPC NEOCP candidate list automatically on startup.
- Calculates ephemerides for both known objects and NEOCP candidates using a single unified workflow.
- No local `fo64.exe`, `find_orb.cfg`, `MPCORB`, or `config.ini` required.
- Supports any MPC observatory code; `X93` is the default GUI value.
- Displays RA/Dec, magnitude, elongation, apparent motion rate and PA, uncertainty, altitude, azimuth, and airmass.
- Computes topocentric Alt/Az and airmass locally with Astropy.
- Shows compact orbital elements, astrometry, residuals, and advanced Project Pluto metadata.
- Integrates with Cartes du Ciel for telescope slewing via TCP (`cartes_du_ciel.py`).
- Includes NEOFIXER target lookup by observatory code.

---

## Requirements

Python 3.10 or newer is recommended.

Install dependencies:

```
python -m pip install -r requirements.txt
```

Required packages:

```
requests
pandas
astropy
```

---

## Running from source

```
python neocp_explorer.py
```

An internet connection is required. The app queries:

- MPC NEOCP JSON list
- Project Pluto online Find_Orb server
- NEOFIXER API (only when the NEOFIXER menu is used)

---

## Using the application

1. Wait for the NEOCP candidate list on the left panel to load.
2. Double-click a candidate to fill the form automatically, or type an object designation manually.
3. Enter your MPC observatory code. The default is `X93`.
4. Enter the number of ephemeris steps.
5. Click **Submit**.

Example object designations:

```
99942
Apophis
2024 MK
A11D0Xd
NAOCYLA
```

The same input field accepts both known object designations and current NEOCP tracklet IDs. The app automatically infers whether the object is a current NEOCP candidate when possible.

---

## Ephemeris columns

| Column      | Meaning                                                         |
|-------------|------------------------------------------------------------------|
| UTC         | Date and time in UTC                                             |
| RA          | Right ascension, J2000/ICRF, from Project Pluto                  |
| Dec         | Declination                                                      |
| Mag         | Approximate visual magnitude                                     |
| Rate "/min  | Apparent sky motion in arcsec per minute                         |
| Mot PA      | Position angle of apparent motion                                |
| Elong       | Solar elongation in degrees                                      |
| Unc. °      | Ephemeris uncertainty in degrees                                  |
| Alt         | Topocentric altitude in degrees, computed locally with Astropy   |
| Az          | Topocentric azimuth in degrees, computed locally with Astropy    |
| Air         | Approximate airmass, shown only for useful altitudes             |

Distance information (geocentric, topocentric, and heliocentric) is shown in the **Summary** tab rather than the ephemeris table.

---

## Cartes du Ciel integration

`cartes_du_ciel.py` provides optional integration with [Cartes du Ciel](https://www.ap-i.net/skychart/en/start) (SkyChart) for telescope slewing. When enabled, NEOCP Explorer sends RA/Dec coordinates to Cartes du Ciel via its TCP server interface, allowing the telescope to be pointed directly at the selected object.

This feature requires Cartes du Ciel to be running locally with its TCP server enabled. Configuration of the host and port is done inside `cartes_du_ciel.py`.

> This integration is desktop-only and depends on a local Cartes du Ciel instance. It is not available in any future web-based version of the tool.

---

## Building an executable

Install PyInstaller if needed:

```
python -m pip install pyinstaller
```

Build:

```
python -m PyInstaller --onefile --windowed --icon=neocp_explorer.ico --add-data "neocp_explorer.ico;." --name="NEOCP_Explorer" neocp_explorer.py
```

The resulting executable is created under `dist/`. No additional files need to be distributed alongside it.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| Project Pluto query failed | Check the designation. The object may not yet be in the MPC/Project Pluto database if it was reported very recently. Also verify the observatory code and internet connection. |
| NEOCP panel failed to load | Check your internet connection and click **Refresh**. |
| Alt/Az not showing | Verify that Astropy is installed (`pip install astropy`). If the observatory code is not in the built-in coordinate table, coordinates for that site need to be added to the source. |
| Cartes du Ciel slewing not working | Confirm Cartes du Ciel is running and its TCP server is enabled. Check that the host and port in `cartes_du_ciel.py` match the CdC settings. |
| App opens and closes immediately | Run `NEOCP_Explorer.exe` from a terminal (`cmd`) to see the error message. |
| Antivirus blocks the .exe | False positive common with PyInstaller executables. Add an exception for `NEOCP_Explorer.exe`. |

---

## Data sources and acknowledgements

NEOCP Explorer relies on several excellent public tools and services:

- **Project Pluto / Find_Orb, by Bill Gray** — online orbit determination and ephemeris service providing orbital elements, residuals, uncertainties, and ephemerides.
- **Minor Planet Center (MPC)** — source of the NEOCP candidate list and minor-planet observational data.
- **Astropy** — used locally for topocentric Alt/Az and airmass calculations.
- **Cartes du Ciel / SkyChart** — optional desktop planetarium and telescope control software.
- **NEOFIXER (University of Arizona)** — optional target-priority information for observatory-specific follow-up planning.

NEOCP Explorer is an independent project and is not affiliated with Project Pluto, the Minor Planet Center, JPL, NEOFIXER, Astropy, or Cartes du Ciel.

---

## Changelog

### v3.1.1 (2026-07-18)
- Fixed deferred MPC NEOCP and Cartes du Ciel error callbacks that could raise `NameError` instead of showing the original failure.
- Captured Tkinter form values on the UI thread before starting background network work.
- Fixed compact orbital-element display for hyperbolic solutions with a negative semi-major axis.
- Aligned Project Pluto fixture generation with the heliocentric production request.
- Added focused regression tests and validated the Windows executable on the Pier 2 observatory PC.

### v3.1 (2026-06-15)
- Renamed the application to **NEOCP Explorer**.
- Forced heliocentric orbital elements, fixing spurious interstellar flags caused by geocentric Find_Orb solutions for short-arc near-Earth objects.
- Handled negative semi-major axis for genuinely hyperbolic heliocentric orbits.
- Added eccentricity uncertainty display and short-arc orbit flag; the interstellar flag now requires a statistically significant hyperbolic excess.

### v3.0
- Removed local Find_Orb dependency (`fo64.exe`).
- Removed `config.ini`.
- Unified known-object and NEOCP workflows into a single input field.
- Added local Alt/Az and airmass computation with Astropy.
- Added apparent motion rate and motion PA columns.
- Improved Project Pluto error handling.
- Simplified distribution for Windows, macOS, and Linux.

### v2.1
- Fixed critical bug where NEO mode produced an empty observation file (OBS80 contamination filter was comparing packed MPC designations against human-readable designations).
- Fixed Submit button permanently locking after an invalid ephemeris steps value.
- Fixed validation error highlight having no visual effect on `ttk.Entry` widgets.
- Corrected NEO dynamical classification (was using Tisserand relative to Earth with Jupiter-family thresholds).
- Fixed altitude column reading position angle instead of actual altitude from Find_Orb output.

### v2.0
- Added object summary panel with PHA and hyperbolic orbit flags.
- Added integrated NEOCP candidate list panel (left pane).

---

---

# Português

## Download

Executáveis pré-compilados para Windows estão disponíveis na [página de Releases](https://github.com/Anduin-source/NEOCP_Explorer/releases).

Não é necessário instalar Python. Baixe a versão mais recente e execute `NEOCP_Explorer.exe` diretamente.

---

## Funcionalidades principais

- Carrega automaticamente a lista atual de candidatos NEOCP do MPC ao iniciar.
- Calcula efemérides para objetos conhecidos e candidatos NEOCP em um único fluxo de trabalho unificado.
- Não requer `fo64.exe`, `find_orb.cfg`, `MPCORB` ou `config.ini` locais.
- Suporta qualquer código de observatório MPC; o valor padrão na interface é `X93`.
- Exibe RA/Dec, magnitude, elongação, taxa e ângulo de posição do movimento aparente, incerteza, altitude, azimute e massa de ar.
- Calcula Alt/Az topocêntrico e massa de ar localmente com o Astropy.
- Mostra elementos orbitais compactos, astrometria, resíduos e metadados avançados do Project Pluto.
- Integra com o Cartes du Ciel para apontamento do telescópio via TCP (`cartes_du_ciel.py`).
- Inclui consulta de alvos NEOFIXER por código de observatório.

---

## Requisitos

Python 3.10 ou superior é recomendado.

Instale as dependências:

```
python -m pip install -r requirements.txt
```

Pacotes necessários:

```
requests
pandas
astropy
```

---

## Rodando pelo código-fonte

```
python neocp_explorer.py
```

É necessária conexão com a internet. O programa consulta:

- Lista JSON NEOCP do MPC
- Servidor online Find_Orb do Project Pluto
- API NEOFIXER (apenas quando o menu NEOFIXER é utilizado)

---

## Usando o programa

1. Aguarde o painel esquerdo com a lista de candidatos NEOCP carregar.
2. Dê um duplo clique em um candidato para preencher o formulário automaticamente, ou digite a designação manualmente.
3. Informe o código de observatório MPC. O padrão é `X93`.
4. Informe o número de passos de efeméride.
5. Clique em **Submit**.

Exemplos de designações aceitas:

```
99942
Apophis
2024 MK
A11D0Xd
NAOCYLA
```

O mesmo campo de entrada aceita tanto designações de objetos conhecidos quanto IDs de tracklets NEOCP atuais. O programa infere automaticamente se o objeto é um candidato NEOCP quando possível.

---

## Colunas da efeméride

| Coluna      | Significado                                                         |
|-------------|----------------------------------------------------------------------|
| UTC         | Data e hora em UTC                                                   |
| RA          | Ascensão reta, J2000/ICRF, calculada pelo Project Pluto              |
| Dec         | Declinação                                                           |
| Mag         | Magnitude visual aproximada                                          |
| Rate "/min  | Taxa de movimento aparente no céu em arcsec por minuto               |
| Mot PA      | Ângulo de posição do movimento aparente                              |
| Elong       | Elongação solar em graus                                             |
| Unc. °      | Incerteza da efeméride em graus                                      |
| Alt         | Altitude topocêntrica em graus, calculada localmente com Astropy     |
| Az          | Azimute topocêntrico em graus, calculado localmente com Astropy      |
| Air         | Massa de ar aproximada, exibida apenas para altitudes úteis          |

Informações de distância (geocêntrica, topocêntrica e heliocêntrica) são exibidas na aba **Summary**, não na tabela de efemérides.

---

## Integração com Cartes du Ciel

O arquivo `cartes_du_ciel.py` oferece integração opcional com o [Cartes du Ciel](https://www.ap-i.net/skychart/en/start) (SkyChart) para apontamento do telescópio. Quando ativado, o NEOCP Explorer envia coordenadas RA/Dec ao Cartes du Ciel via interface TCP, permitindo apontar o telescópio diretamente para o objeto selecionado.

Este recurso requer que o Cartes du Ciel esteja em execução localmente com o servidor TCP habilitado. O host e a porta são configurados dentro do arquivo `cartes_du_ciel.py`.

> Esta integração é exclusiva para a versão desktop e depende de uma instância local do Cartes du Ciel. Não estará disponível em eventuais versões web do programa.

---

## Gerando o executável

Instale o PyInstaller se necessário:

```
python -m pip install pyinstaller
```

Gere o executável:

```
python -m PyInstaller --onefile --windowed --icon=neocp_explorer.ico --add-data "neocp_explorer.ico;." --name="NEOCP_Explorer" neocp_explorer.py
```

O executável é gerado na pasta `dist/`. Nenhum arquivo adicional precisa ser distribuído junto com ele.

---

## Solução de problemas

| Problema | Solução |
|---|---|
| Consulta ao Project Pluto falhou | Verifique a designação. O objeto pode ainda não estar na base de dados do MPC/Project Pluto se foi reportado muito recentemente. Verifique também o código de observatório e a conexão com a internet. |
| Painel NEOCP não carregou | Verifique a conexão com a internet e clique em **Refresh**. |
| Alt/Az não aparece | Verifique se o Astropy está instalado (`pip install astropy`). Se o código de observatório não estiver na tabela de coordenadas embutida, as coordenadas desse sítio precisam ser adicionadas ao código-fonte. |
| Apontamento via Cartes du Ciel não funciona | Confirme que o Cartes du Ciel está em execução e com o servidor TCP habilitado. Verifique se o host e a porta em `cartes_du_ciel.py` correspondem às configurações do CdC. |
| Programa abre e fecha imediatamente | Execute `NEOCP_Explorer.exe` a partir de um terminal (`cmd`) para ver a mensagem de erro. |
| Antivírus bloqueia o .exe | Falso positivo comum em executáveis gerados pelo PyInstaller. Adicione uma exceção para `NEOCP_Explorer.exe`. |

---

## Fontes de dados e agradecimentos

O NEOCP Explorer depende de excelentes ferramentas e serviços públicos:

- **Project Pluto / Find_Orb, por Bill Gray** — serviço online de determinação de órbita e efemérides, fornecendo elementos orbitais, resíduos, incertezas e efemérides.
- **Minor Planet Center (MPC)** — fonte da lista de candidatos NEOCP e dados observacionais de pequenos planetas.
- **Astropy** — utilizado localmente para cálculos de Alt/Az topocêntrico e massa de ar.
- **Cartes du Ciel / SkyChart** — software opcional de planetário e controle de telescópio.
- **NEOFIXER (Universidade do Arizona)** — informações opcionais de prioridade de alvos para planejamento de follow-up por observatório.

O NEOCP Explorer é um projeto independente e não tem afiliação com o Project Pluto, o Minor Planet Center, o JPL, o NEOFIXER, o Astropy ou o Cartes du Ciel.

---

## Histórico de versões

### v3.1.1 (2026-07-18)
- Corrigidos os callbacks adiados de erro do MPC NEOCP e do Cartes du Ciel, que podiam gerar `NameError` em vez de mostrar a falha original.
- Os valores do formulário Tkinter agora são capturados na thread da interface antes do trabalho de rede em segundo plano.
- Corrigida a exibição compacta de elementos orbitais para soluções hiperbólicas com semieixo maior negativo.
- O gerador de fixtures do Project Pluto foi alinhado à requisição heliocêntrica usada em produção.
- Adicionados testes de regressão direcionados e validado o executável Windows no computador do observatório Pier 2.

### v3.1 (2026-06-15)
- Programa renomeado para **NEOCP Explorer**.
- Elementos orbitais heliocentricos forçados, corrigindo flags espúrias de objeto interestelar causadas por soluções geocêntricas do Find_Orb para objetos com arco observacional curto.
- Tratamento de semi-eixo maior negativo para órbitas genuinamente hiperbólicas.
- Exibição da incerteza na excentricidade e flag de órbita com arco curto; o flag interestelar agora exige excesso hiperbólico estatisticamente significativo.

### v3.0
- Removida dependência do Find_Orb local (`fo64.exe`).
- Removido `config.ini`.
- Unificados os fluxos de objetos conhecidos e NEOCP em um único campo de entrada.
- Adicionado cálculo local de Alt/Az e massa de ar com Astropy.
- Adicionadas colunas de taxa de movimento aparente e ângulo de posição.
- Melhorado o tratamento de erros do Project Pluto.
- Distribuição simplificada para Windows, macOS e Linux.

### v2.1
- Corrigido bug crítico em que o modo NEO gerava arquivo de observações vazio (filtro de contaminação OBS80 comparava designações MPC compactadas com designações legíveis por humanos).
- Corrigido travamento permanente do botão Submit após valor inválido no campo de passos de efeméride.
- Corrigido destaque de erro de validação sem efeito visual em widgets `ttk.Entry`.
- Corrigida classificação dinâmica de NEOs (usava Tisserand relativo à Terra com limiares de família de Júpiter).
- Corrigida leitura da coluna de altitude que lia ângulo de posição em vez da altitude real na saída do Find_Orb.

### v2.0
- Adicionado painel de resumo do objeto com flags de APH e órbita hiperbólica.
- Adicionado painel integrado de lista de candidatos NEOCP (painel esquerdo).

---

*Data sources: Minor Planet Center · Project Pluto / Find_Orb by Bill Gray · Astropy · NEOFIXER by University of Arizona · Cartes du Ciel*
