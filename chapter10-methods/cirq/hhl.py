"""
Demonstrates the algorithm for solving linear systems by Harrow, Hassidim,
Lloyd (HHL).

The HHL algorithm solves a system of linear equations, specifically equations
of the form Ax = b, where A is a Hermitian matrix, b is a known vector, and
x is the unknown vector. To solve on a quantum system, b must be rescaled to
have magnitude 1, and the equation becomes:

|x> = A**-1 |b> / || A**-1 |b> ||

The algorithm uses 3 sets of qubits: a single ancilla qubit, a register (to
store eigenvalues of A), and memory qubits (to store |b> and |x>). The
following are performed in order:

1) Quantum phase estimation to extract eigenvalues of A
2) Controlled rotations of ancilla qubit
3) Uncomputation with inverse quantum phase estimation

For details about the algorithm, please refer to papers in the
REFERENCE section below. The following description uses variables defined
in the HHL paper.

This example is an implementation of the HHL algorithm for arbitrary 2x2
Hermitian matrices. The output of the algorithm is a display of Pauli
observables of |x>. Note that the accuracy of the result depends on the
following factors:

* Register size
* Choice of parameters C and t

The result is perfect if
* Each eigenvalue of the matrix is in the form
  2π/t * k/N,
  where 0≤k<N, and N=2^n, where n is the register size. In other words, k is a
  value that can be represented exactly by the register.
* C ≤ 2π/t * 1/N, the smallest eigenvalue that can be stored in the circuit.

The result is good if the register size is large enough such that for every
pair of eigenvalues, the ratio can be approximated by a pair of possible
register values. Let s be the scaling factor from possible register values to
eigenvalues. One way to set t is

t = 2π/sN

For arbitrary matrices, because properties of their eigenvalues are typically
unknown, parameters C and t are fine-tuned based on their condition number.


=== REFERENCE ===

Harrow, Aram W. et al. Quantum algorithm for solving linear systems of
equations (the HHL paper)

https://arxiv.org/abs/0811.3171

Coles, Eidenbenz et al. Quantum Algorithm Implementations for Beginners

https://arxiv.org/abs/1804.03719


=== CIRCUIT ===


Example of circuit with 2 register qubits.

(0, 0): ─────────────────────────Ry(θ₄)─Ry(θ₁)─Ry(θ₂)─Ry(θ₃)──────────────M──
                     ┌──────┐    │      │      │      │ ┌───┐
(1, 0): ─H─@─────────│      │──X─@──────@────X─@──────@─│   │─────────@─H────
           │         │QFT^-1│    │      │      │      │ │QFT│         │
(2, 0): ─H─┼─────@───│      │──X─@────X─@────X─@────X─@─│   │─@───────┼─H────
           │     │   └──────┘                           └───┘ │       │
(3, 0): ───e^iAt─e^2iAt───────────────────────────────────────e^-2iAt─e^-iAt─


Note: QFT in the above diagram omits swaps, which are included implicitly by
reversing qubit order for phase kickbacks.
"""

import math
import numpy as np
import cirq


class PhaseEstimation(cirq.Gate):
    """
    A gate for Quantum Phase Estimation.
    unitary is the unitary gate whose phases will be estimated.
    The last qubit stores the eigenvector; all other qubits store the
    estimated phase, in big-endian.
    """

    def __init__(self, num_qubits, unitary):
        super(PhaseEstimation, self)
        self._num_qubits = num_qubits
        self.U = unitary

    def num_qubits(self):
        return self._num_qubits

    def _decompose_(self, qubits):
        qubits = list(qubits)
        yield cirq.H.on_each(*qubits[:-1])
        yield PhaseKickback(self.num_qubits(), self.U)(*qubits)
        yield Qft(self._num_qubits-1)(*qubits[:-1])**-1


class HamiltonianSimulation(cirq.EigenGate, cirq.SingleQubitGate):
    """
    A gate that represents e^iAt.
    This EigenGate + np.linalg.eigh() implementation is used here
    purely for demonstrative purposes. If a large matrix is used,
    the circuit should implement actual Hamiltonian simulation,
    by using the linear operators framework in Cirq for example.
    """

    def __init__(self, A, t, exponent=1.0):
        cirq.SingleQubitGate.__init__(self)
        cirq.EigenGate.__init__(self, exponent=exponent)
        self.A = A
        self.t = t
        ws, vs = np.linalg.eigh(A)
        self.eigen_components = []
        for w, v in zip(ws, vs.T):
            theta = w*t / math.pi
            P = np.outer(v, np.conj(v))
            self.eigen_components.append((theta, P))

    def _with_exponent(self, exponent):
        return HamiltonianSimulation(self.A, self.t, exponent)

    def _eigen_components(self):
        return self.eigen_components


class PhaseKickback(cirq.Gate):
    """
    A gate for the phase kickback stage of Quantum Phase Estimation.
    It consists of a series of controlled e^iAt gates with the memory qubit as
    the target and each register qubit as the control, raised
    to the power of 2 based on the qubit index.
    unitary is the unitary gate whose phases will be estimated.
    """

    def __init__(self, num_qubits, unitary):
        super(PhaseKickback, self)
        self._num_qubits = num_qubits
        self.U = unitary

    def num_qubits(self):
        return self._num_qubits

    def _decompose_(self, qubits):
        qubits = list(qubits)
        memory = qubits.pop()
        for i, qubit in enumerate(qubits):
            yield cirq.ControlledGate(self.U**(2**i))(qubit, memory)


class Qft(cirq.Gate):
    """
    Quantum gate for the Quantum Fourier Transformation.
    Swaps are omitted here because it's done implicitly in the PhaseKickback
    gate by reversing the control qubit order.
    """

    def __init__(self, num_qubits):
        super(Qft, self)
        self._num_qubits = num_qubits

    def num_qubits(self):
        return self._num_qubits

    def _decompose_(self, qubits):
        processed_qubits = []
        for q_head in qubits:
            for i, qubit in enumerate(processed_qubits):
                yield cirq.CZ(qubit, q_head)**(1/2.0**(i+1))
            yield cirq.H(q_head)
            processed_qubits.insert(0, q_head)


class EigenRotation(cirq.Gate):
    """
    EigenRotation performs the set of rotation on the ancilla qubit equivalent
    to division on the memory register by each eigenvalue of the matrix. The
    last qubit is the ancilla qubit; all remaining qubits are the register,
    assumed to be big-endian.
    It consists of a controlled ancilla qubit rotation for each possible value
    that can be represented by the register. Each rotation is a Ry gate where
    the angle is calculated from the eigenvalue corresponding to the register
    value, up to a normalization factor C.
    """

    def __init__(self, num_qubits, C, t):
        super(EigenRotation, self)
        self._num_qubits = num_qubits
        self.C = C
        self.t = t
        self.N = 2**(num_qubits-1)

    def num_qubits(self):
        return self._num_qubits

    def _decompose_(self, qubits):
        for k in range(self.N):
            kGate = self._ancilla_rotation(k)

            # xor's 1 bits correspond to X gate positions.
            xor = k ^ (k-1)

            for q in qubits[-2::-1]:
                # Place X gates
                if xor % 2 == 1:
                    yield cirq.X(q)
                xor >>= 1

                # Build controlled ancilla rotation
                kGate = cirq.ControlledGate(kGate)

            yield kGate(*qubits)

    def _ancilla_rotation(self, k):
        if k == 0:
            k = self.N
        theta = 2*math.asin(self.C * self.N * self.t / (2*math.pi * k))
        return cirq.Ry(theta)


def hhl_circuit(A, C, t, register_size, *input_prep_gates):
    """
    Constructs the HHL circuit.
    A is the input Hermitian matrix.
    C and t are tunable parameters for the algorithm.
    register_size is the size of the eigenvalue register.
    input_prep_gates is a list of gates to be applied to |0> to generate the
      desired input state |b>.
    """

    ancilla = cirq.GridQubit(0, 0)
    # to store eigenvalues of the matrix
    register = [cirq.GridQubit(i+1, 0) for i in range(register_size)]
    # to store input and output vectors
    memory = cirq.GridQubit(register_size+1, 0)

    c = cirq.Circuit()
    hs = HamiltonianSimulation(A, t)
    pe = PhaseEstimation(register_size+1, hs)
    c.append([gate(memory) for gate in input_prep_gates])
    c.append([
        pe(*(register + [memory])),
        EigenRotation(register_size+1, C, t)(*(register+[ancilla])),
        pe(*(register + [memory]))**-1,
        cirq.measure(ancilla)
    ])

    # Pauli observable display
    c.append([
        cirq.pauli_string_expectation(
            cirq.PauliString({ancilla: cirq.Z}),
            key='a'
        ),
        cirq.pauli_string_expectation(
            cirq.PauliString({memory: cirq.X}),
            key='x'
        ),
        cirq.pauli_string_expectation(
            cirq.PauliString({memory: cirq.Y}),
            key='y'
        ),
        cirq.pauli_string_expectation(
            cirq.PauliString({memory: cirq.Z}),
            key='z'
        ),
    ])

    return c


def simulate(circuit):
    simulator = cirq.Simulator()

    # TODO optimize using amplitude amplification algorithm
    ancilla_expectation = 0.0
    while ancilla_expectation != -1.0:
        result = simulator.compute_displays(circuit)
        ancilla_expectation = round(result.display_values['a'], 3)

    # Compute displays
    print('X = {}'.format(result.display_values['x']))
    print('Y = {}'.format(result.display_values['y']))
    print('Z = {}'.format(result.display_values['z']))


def main():
    """
    Simulates HHL with matrix input, and outputs Pauli observables of the
    resulting qubit state |x>.
    Expected observables are calculated from the expected solution |x>.
    """
    # Constants
    t = 0.358166 * math.pi
    register_size = 4

    # Eigendecomposition:
    #   (4.537, [-0.971555, -0.0578339+0.229643j])
    #   (0.349, [-0.236813, 0.237270-0.942137j])
    # |b> = (0.64510-0.47848j, 0.35490-0.47848j)
    # |x> = (-0.0662724-0.214548j, 0.784392-0.578192j)
    A = np.array([[4.30213466-6.01593490e-08j,
                   0.23531802+9.34386156e-01j],
                  [0.23531882-9.34388383e-01j,
                   0.58386534+6.01593489e-08j]])
    input_prep_gates = [cirq.Rx(1.276359), cirq.Rz(1.276359)]
    expected = (0.144130, 0.413217, -0.899154)

    # Set C to be the smallest eigenvalue that can be represented by the
    # circuit.
    C = 2*math.pi / (2**register_size * t)

    # Simulate circuit
    print("Expected observable outputs:")
    print("X =", expected[0])
    print("Y =", expected[1])
    print("Z =", expected[2])
    print("Actual: ")
    hhlcirc = hhl_circuit(A, C, t, register_size, *input_prep_gates)
    print(hhlcirc)
    simulate(hhlcirc)


if __name__ == '__main__':
    main()