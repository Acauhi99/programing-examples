"""Exemplo didático de composição de classes para um motor a gasolina.

O modelo usa valores médios por intervalo de tempo, como modelos simplificados
de controle de motor. Ele representa partida, fluxo de ar e combustível, torque,
atrito, inércia e temperaturas. Não calcula cada cilindro ou cada grau do
virabrequim e não prevê emissões, detonação ou desempenho de um veículo real.

Execute com: python motor_combustao.py
"""

from dataclasses import dataclass, field
from math import exp, pi
from typing import Optional


def limitar(valor: float, minimo: float, maximo: float) -> float:
    return max(minimo, min(valor, maximo))


@dataclass(frozen=True)
class Combustivel:
    nome: str = "gasolina"
    afr_estequiometrica: float = 14.7  # kg de ar para 1 kg de combustível
    poder_calorifico_j_kg: float = 43_000_000.0


@dataclass(frozen=True)
class GeometriaMotor:
    cilindros: int = 4
    cilindrada_m3: float = 2.433e-3  # 2,433 litros
    taxa_compressao: float = 10.5
    eficiencia_volumetrica: float = 0.88


@dataclass
class SistemaAdmissao:
    pressao_ambiente_pa: float = 101_325.0
    temperatura_ar_k: float = 300.0
    pressao_coletor_pa: float = 101_325.0
    constante_tempo_s: float = 0.12

    def avancar(self, abertura: float, dt: float) -> None:
        # A pressão do coletor não acompanha a borboleta instantaneamente.
        pressao_alvo = self.pressao_ambiente_pa * (
            0.05 + 0.95 * abertura**0.65
        )
        fracao = 1.0 - exp(-dt / self.constante_tempo_s)
        self.pressao_coletor_pa += fracao * (
            pressao_alvo - self.pressao_coletor_pa
        )

    def calcular_vazao_ar(self, geometria: GeometriaMotor, rpm: float) -> float:
        if rpm <= 0.0:
            return 0.0

        # Em um motor de quatro tempos, cada cilindro admite ar a cada duas voltas.
        volume_admitido_m3_s = (
            geometria.cilindrada_m3 * rpm / 120.0
            * geometria.eficiencia_volumetrica
        )
        densidade_ar_kg_m3 = self.pressao_coletor_pa / (
            287.05 * self.temperatura_ar_k
        )
        return volume_admitido_m3_s * densidade_ar_kg_m3


@dataclass
class SistemaInjecao:
    corte_por_desaceleracao: bool = False

    def calcular_vazao_combustivel(
        self,
        vazao_ar_kg_s: float,
        combustivel: Combustivel,
        rpm: float,
        abertura: float,
        temperatura_liquido_c: float,
        partida_acionada: bool,
        limitador_ativo: bool,
    ) -> tuple[float, Optional[float]]:
        if limitador_ativo:
            return 0.0, None

        # A injeção corta combustível em desaceleração e o retoma perto da marcha lenta.
        if abertura < 0.10 and rpm > 1_500.0:
            self.corte_por_desaceleracao = True
        elif rpm < 1_200.0 or abertura >= 0.10:
            self.corte_por_desaceleracao = False

        if self.corte_por_desaceleracao or vazao_ar_kg_s <= 0.0:
            return 0.0, None

        # Mistura um pouco mais rica em alta carga e durante aquecimento/partida.
        lambda_alvo = 0.88 if abertura > 0.80 else 0.98
        enriquecimento_frio = 1.0 + limitar(
            (60.0 - temperatura_liquido_c) * 0.003, 0.0, 0.20
        )
        enriquecimento_partida = 1.15 if partida_acionada else 1.0
        vazao = (
            vazao_ar_kg_s
            / (combustivel.afr_estequiometrica * lambda_alvo)
            * enriquecimento_frio
            * enriquecimento_partida
        )
        lambda_real = vazao_ar_kg_s / (
            vazao * combustivel.afr_estequiometrica
        )
        return vazao, lambda_real


@dataclass
class SistemaIgnicao:
    avanco_graus: float = 0.0

    def fator_queima(self, rpm: float, abertura: float) -> float:
        if rpm < 250.0:
            return 0.0  # abaixo da rotação de partida não há combustão estável

        # Curva simples de avanço: mais avanço com rotação, menos em alta carga.
        self.avanco_graus = limitar(
            8.0 + rpm * 0.004 - abertura * 4.0, 8.0, 32.0
        )
        return 0.96


@dataclass
class MotorDePartida:
    torque_maximo_nm: float = 95.0
    rotacao_desligamento_rpm: float = 600.0
    acionado: bool = False

    def acionar(self) -> None:
        self.acionado = True

    def calcular_torque(self, rpm: float) -> float:
        if not self.acionado:
            return 0.0
        if rpm >= self.rotacao_desligamento_rpm:
            self.acionado = False
            return 0.0

        # O torque do motor de partida cai conforme sua velocidade aumenta.
        fracao_rotacao = rpm / self.rotacao_desligamento_rpm
        return self.torque_maximo_nm * (1.0 - 0.65 * fracao_rotacao)


@dataclass
class Virabrequim:
    momento_inercia_kg_m2: float = 0.22
    rpm: float = 0.0

    def avancar(self, torque_liquido_nm: float, dt: float) -> None:
        velocidade_angular = self.rpm * 2.0 * pi / 60.0
        aceleracao_angular = torque_liquido_nm / self.momento_inercia_kg_m2
        velocidade_angular = max(
            0.0, velocidade_angular + aceleracao_angular * dt
        )
        self.rpm = velocidade_angular * 60.0 / (2.0 * pi)


@dataclass
class SistemaArrefecimento:
    temperatura_liquido_c: float = 20.0
    temperatura_ambiente_c: float = 25.0
    massa_liquido_kg: float = 8
    capacidade_calorifica_j_kg_k: float = 4_180.0
    condutancia_radiador_w_k: float = 500.0

    def avancar(self, potencia_combustivel_w: float, dt: float) -> None:
        # Aproximadamente 22% da energia do combustível aquece o líquido.
        calor_motor_w = potencia_combustivel_w * 0.22
        abertura_termostato = limitar(
            (self.temperatura_liquido_c - 80.0) / 10.0, 0.0, 1.0
        )
        calor_radiador_w = (
            self.condutancia_radiador_w_k
            * abertura_termostato
            * max(0.0, self.temperatura_liquido_c - self.temperatura_ambiente_c)
        )
        capacidade_termica_j_k = (
            self.massa_liquido_kg * self.capacidade_calorifica_j_kg_k
        )
        self.temperatura_liquido_c += (
            (calor_motor_w - calor_radiador_w)
            * dt
            / capacidade_termica_j_k
        )


@dataclass
class SistemaLubrificacao:
    temperatura_oleo_c: float = 20.0
    capacidade_termica_j_k: float = 15_000.0

    def avancar(
        self,
        potencia_atrito_w: float,
        temperatura_liquido_c: float,
        temperatura_ambiente_c: float,
        dt: float,
    ) -> None:
        calor_atrito_w = max(0.0, potencia_atrito_w) * 0.45
        troca_com_liquido_w = 75.0 * (
            temperatura_liquido_c - self.temperatura_oleo_c
        )
        perda_ambiente_w = 14.0 * (
            self.temperatura_oleo_c - temperatura_ambiente_c
        )
        self.temperatura_oleo_c += (
            (calor_atrito_w + troca_com_liquido_w - perda_ambiente_w)
            * dt
            / self.capacidade_termica_j_k
        )

    def pressao_bar(self, rpm: float) -> float:
        pressao_base = min(5.0, 0.7 + rpm * 0.00065)
        fator_viscosidade = limitar(
            1.25 - max(0.0, self.temperatura_oleo_c - 20.0) * 0.004,
            0.65,
            1.25,
        )
        return pressao_base * fator_viscosidade


@dataclass
class UnidadeControleMotor:
    rpm_marcha_lenta: float = 850.0
    _integral_marcha_lenta: float = 0.0

    def calcular_abertura(
        self, pedal: float, rpm: float, dt: float, motor_ligado: bool
    ) -> float:
        if pedal > 0.03:
            self._integral_marcha_lenta = 0.0
            return pedal

        if not motor_ligado:
            return 0.18  # abertura de ar para a partida e a marcha lenta

        erro = self.rpm_marcha_lenta - rpm
        self._integral_marcha_lenta = limitar(
            self._integral_marcha_lenta + erro * dt * 0.00008,
            -0.12,
            0.18,
        )
        abertura = 0.17 + erro * 0.00025 + self._integral_marcha_lenta
        return limitar(abertura, 0.08, 0.38)


@dataclass(frozen=True)
class LeituraMotor:
    rpm: float
    ligado: bool
    abertura_acelerador: float
    pressao_coletor_kpa: float
    vazao_ar_kg_s: float
    vazao_combustivel_kg_s: float
    lambda_mistura: Optional[float]
    torque_motor_nm: float
    torque_carga_nm: float
    potencia_eixo_kw: float
    temperatura_liquido_c: float
    temperatura_oleo_c: float
    pressao_oleo_bar: float
    avanco_ignicao_graus: float


@dataclass
class MotorCombustao:
    geometria: GeometriaMotor = field(default_factory=GeometriaMotor)
    combustivel: Combustivel = field(default_factory=Combustivel)
    admissao: SistemaAdmissao = field(default_factory=SistemaAdmissao)
    injecao: SistemaInjecao = field(default_factory=SistemaInjecao)
    ignicao: SistemaIgnicao = field(default_factory=SistemaIgnicao)
    partida: MotorDePartida = field(default_factory=MotorDePartida)
    virabrequim: Virabrequim = field(default_factory=Virabrequim)
    arrefecimento: SistemaArrefecimento = field(default_factory=SistemaArrefecimento)
    lubrificacao: SistemaLubrificacao = field(default_factory=SistemaLubrificacao)
    controle: UnidadeControleMotor = field(default_factory=UnidadeControleMotor)
    ligado: bool = False
    _limitador_ativo: bool = False

    def dar_partida(self) -> None:
        if not self.ligado:
            self.partida.acionar()

    def avancar(
        self,
        dt: float,
        pedal: float = 0.0,
        torque_carga_nm: float = 0.0,
    ) -> LeituraMotor:
        """Avança o motor por ``dt`` segundos.

        Use passos de até 0,05 s. ``torque_carga_nm`` é o torque aplicado ao
        virabrequim por uma transmissão ou máquina acoplada.
        """
        if not 0.0 < dt <= 0.05:
            raise ValueError("dt deve estar entre 0 e 0,05 segundo")
        if not 0.0 <= pedal <= 1.0:
            raise ValueError("pedal deve estar entre 0 e 1")
        if torque_carga_nm < 0.0:
            raise ValueError("torque_carga_nm não pode ser negativo")

        rpm = self.virabrequim.rpm
        if self.ligado and rpm < 250.0:
            self.ligado = False  # o motor apagou

        abertura = self.controle.calcular_abertura(
            pedal, rpm, dt, self.ligado
        )
        self.admissao.avancar(abertura, dt)
        vazao_ar = self.admissao.calcular_vazao_ar(self.geometria, rpm)

        if rpm >= 6_500.0:
            self._limitador_ativo = True
        elif rpm <= 6_200.0:
            self._limitador_ativo = False

        partida_acionada = self.partida.acionado
        vazao_combustivel, lambda_mistura = (
            self.injecao.calcular_vazao_combustivel(
                vazao_ar,
                self.combustivel,
                rpm,
                abertura,
                self.arrefecimento.temperatura_liquido_c,
                partida_acionada,
                self._limitador_ativo,
            )
            if rpm >= 250.0 and (self.ligado or partida_acionada)
            else (0.0, None)
        )

        fator_queima = self.ignicao.fator_queima(rpm, abertura)
        potencia_combustivel = (
            vazao_combustivel * self.combustivel.poder_calorifico_j_kg
        )
        eficiencia_otto_ideal = 1.0 - 1.0 / (
            self.geometria.taxa_compressao**0.35
        )
        eficiencia_ciclo = (
            eficiencia_otto_ideal
            * 0.58
            * (0.40 + 0.60 * abertura)
        )
        potencia_indicada = (
            potencia_combustivel * eficiencia_ciclo * fator_queima
        )

        # Perdas médias por bombeamento e atrito mecânico (pressão média efetiva).
        potencia_bombeamento = (
            max(
                0.0,
                self.admissao.pressao_ambiente_pa
                - self.admissao.pressao_coletor_pa,
            )
            * self.geometria.cilindrada_m3
            * rpm
            / 120.0
        )
        pressao_atrito_pa = 55_000.0 + 10.0 * rpm
        potencia_atrito = (
            pressao_atrito_pa * self.geometria.cilindrada_m3 * rpm / 120.0
        )

        velocidade_angular = rpm * 2.0 * pi / 60.0
        potencia_acessorios = 180.0 if self.ligado else 0.0
        potencia_eixo = (
            potencia_indicada
            - potencia_bombeamento
            - potencia_atrito
            - potencia_acessorios
        )
        torque_motor = (
            potencia_eixo / velocidade_angular if velocidade_angular > 0.0 else 0.0
        )
        torque_partida = self.partida.calcular_torque(rpm)
        torque_liquido = torque_motor + torque_partida - torque_carga_nm
        self.virabrequim.avancar(torque_liquido, dt)

        if self.partida.acionado and self.virabrequim.rpm >= 250.0:
            self.ligado = True
        if self.virabrequim.rpm < 250.0 and not self.partida.acionado:
            self.ligado = False

        self.arrefecimento.avancar(potencia_combustivel, dt)
        self.lubrificacao.avancar(
            potencia_atrito,
            self.arrefecimento.temperatura_liquido_c,
            self.arrefecimento.temperatura_ambiente_c,
            dt,
        )

        return LeituraMotor(
            rpm=self.virabrequim.rpm,
            ligado=self.ligado,
            abertura_acelerador=abertura,
            pressao_coletor_kpa=self.admissao.pressao_coletor_pa / 1_000.0,
            vazao_ar_kg_s=vazao_ar,
            vazao_combustivel_kg_s=vazao_combustivel,
            lambda_mistura=lambda_mistura,
            torque_motor_nm=torque_motor,
            torque_carga_nm=torque_carga_nm,
            potencia_eixo_kw=potencia_eixo / 1_000.0,
            temperatura_liquido_c=self.arrefecimento.temperatura_liquido_c,
            temperatura_oleo_c=self.lubrificacao.temperatura_oleo_c,
            pressao_oleo_bar=self.lubrificacao.pressao_bar(
                self.virabrequim.rpm
            ),
            avanco_ignicao_graus=self.ignicao.avanco_graus,
        )


def demonstracao() -> None:
    motor = MotorCombustao()
    motor.dar_partida()

    print(
        "tempo  rpm   pedal  MAP   torque  carga  gasolina  "
        "liquido  oleo"
    )
    print(
        "(s)          (0-1) (kPa)  (N.m)  (N.m)    (g/s)    "
        "(°C)   (bar)"
    )

    dt = 0.01
    duracao_s = 12.0
    amostrar_a_cada_s = 0.5
    proxima_amostra = 0.0
    tempo = 0.0

    while tempo < duracao_s:
        if tempo < 2.0:
            pedal, carga = 0.0, 0.0
        elif tempo < 5.0:
            pedal, carga = 0.35, 20.0
        elif tempo < 8.0:
            pedal, carga = 0.65, 75.0
        else:
            pedal, carga = 0.0, 0.0

        leitura = motor.avancar(dt, pedal, carga)
        if tempo + 1e-9 >= proxima_amostra:
            print(
                f"{tempo:5.1f} {leitura.rpm:5.0f}  {pedal:5.2f} "
                f"{leitura.pressao_coletor_kpa:5.1f} "
                f"{leitura.torque_motor_nm:7.1f} "
                f"{carga:6.1f} "
                f"{leitura.vazao_combustivel_kg_s * 1_000:8.2f} "
                f"{leitura.temperatura_liquido_c:7.1f} "
                f"{leitura.pressao_oleo_bar:6.2f}"
            )
            proxima_amostra += amostrar_a_cada_s
        tempo += dt


if __name__ == "__main__":
    demonstracao()
