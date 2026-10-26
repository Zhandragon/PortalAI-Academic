"""Small CPU-only material-point demonstration; not a validated CFD solver.

Quadratic APIC transfers, a compressible liquid equation of state, corotated
elastic stress and momentum-exchanging contact with a translating rigid sphere.
2D means a one-metre-thick slice. No gas, biological transport or reaction model.
See Documentation/Coupled_Physics_Demo_20261010.txt for assumptions and sources.
"""
from __future__ import annotations

import itertools
import math
import time

import numpy as np

LIMITATIONS = [
    'Educational coarse simulation, not validated engineering CFD or a predictive virtual world.',
    'Water-like liquid uses artificially reduced bulk stiffness; it is not quantitatively accurate water.',
    'Shared-grid liquid/elastic contact can be artificially sticky; no fracture, turbulence, surface tension or air solver.',
    'The rigid disk/sphere translates and exchanges normal momentum; rotation, joints and arbitrary CAD bodies are unsupported.',
    '2D results assume unit out-of-plane thickness; CPU implementation only, with bounded resolution and runtime.',
]


def settings(payload):
    allowed = {'dimensions', 'grid', 'duration_s', 'frames', 'output_dir'}
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError('Unsupported coupled-demo fields: ' + ', '.join(sorted(unknown)))
    def integer(key, default, low, high):
        value = payload.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f'{key} must be an integer from {low} to {high}')
        return value
    dimension = integer('dimensions', 2, 2, 3)
    grid = integer('grid', 28 if dimension == 2 else 24, 24, 40 if dimension == 2 else 28)
    frames = integer('frames', 31, 2, 61)
    duration = payload.get('duration_s', .5)
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or not .02 <= duration <= 1.:
        raise ValueError('duration_s must be finite and between 0.02 and 1.0 seconds')
    return {'dimensions': dimension, 'grid': grid, 'duration_s': float(duration), 'frames': frames}


def stress(deformation, liquid):
    """Kirchhoff stress: objective corotated solid, isotropic liquid pressure."""
    d = deformation.shape[-1]
    identity = np.eye(d)
    jacobian = np.linalg.det(deformation)
    if not np.isfinite(jacobian).all() or (jacobian < .2).any() or (jacobian > 5).any():
        raise RuntimeError('Demo deformation left its supported stability range; reduce duration or increase resolution.')
    u, _, vh = np.linalg.svd(deformation)
    rotation = u @ vh
    # E=50000 Pa, nu=.25; Tait liquid bulk stiffness=250000 Pa (reduced).
    mu, lam = 20000., 20000.
    tau = 2 * mu * ((deformation - rotation) @ deformation.transpose(0, 2, 1))
    tau += (lam * jacobian * (jacobian - 1))[:, None, None] * identity
    tau[liquid] = (250000 / 7 * (jacobian[liquid] - jacobian[liquid]**-6))[:, None, None] * identity
    return tau, jacobian


def contact(positions, velocities, masses, center, body_velocity, radius, body_mass):
    """Frictionless normal contact; equal/opposite linear momentum by construction."""
    delta = positions - center
    lengths = np.linalg.norm(delta, axis=1)
    mask = (lengths < radius) & (lengths > 1e-10) & (masses > 1e-12)
    indices = np.flatnonzero(mask)
    if not len(indices):
        return 0., 0
    normal = delta[indices] / lengths[indices, None]
    approaching = np.minimum(np.sum((velocities[indices] - body_velocity) * normal, axis=1), 0.)
    # Collective effective mass keeps simultaneous grid contacts bounded.
    factor = body_mass / (body_mass + masses[indices].sum())
    change = -approaching[:, None] * normal * factor
    impulse = (masses[indices, None] * change).sum(axis=0)
    velocities[indices] += change
    body_velocity -= impulse / body_mass
    return float(np.linalg.norm(impulse)), int(np.count_nonzero(approaching))


class CoupledDemo:
    def __init__(self, config):
        self.config = dict(config)
        self.d, self.n = config['dimensions'], config['grid']
        self.dx = 1. / self.n
        spacing = self.dx * (.75 if self.d == 2 else 1.)
        def block(low, high):
            axes = [np.arange(a + spacing / 2, b, spacing) for a, b in zip(low, high)]
            return np.array(list(itertools.product(*axes)), dtype=float)
        if self.d == 2:
            water = block([.18, .18], [.51, .43])
            elastic = block([.57, .18], [.74, .44])
            self.body_center = np.array([.43, .63])
        else:
            water = block([.18, .3, .18], [.51, .7, .43])
            elastic = block([.57, .4, .18], [.74, .6, .44])
            self.body_center = np.array([.43, .5, .63])
        self.x = np.concatenate([water, elastic])
        if not 0 < len(self.x) <= 2000:
            raise ValueError('Demo particle allocation exceeds its bounded inventory')
        self.liquid = np.arange(len(self.x)) < len(water)
        self.v = np.zeros_like(self.x)
        self.affine = np.zeros((len(self.x), self.d, self.d))
        self.deformation = np.tile(np.eye(self.d), (len(self.x), 1, 1))
        self.volume = spacing ** self.d
        self.masses = np.full(len(self.x), 1000. * self.volume)
        self.radius = .075
        self.body_mass = 650. * (math.pi * self.radius**2 if self.d == 2 else 4 / 3 * math.pi * self.radius**3)
        self.body_velocity = np.zeros(self.d)
        self.grid_positions = np.indices((self.n,) * self.d).reshape(self.d, -1).T * self.dx
        self.grid_mass = np.zeros(self.n ** self.d)
        self.grid_v = np.zeros((self.n ** self.d, self.d))
        self.offsets = list(itertools.product(range(3), repeat=self.d))
        self.gravity = np.zeros(self.d); self.gravity[-1] = -9.80665
        self.time = 0.; self.contact_count = 0; self.contact_impulse = 0.
        self.max_mass_error = 0.; self.max_volume_error = 0.

    def stencil(self):
        base = np.floor(self.x / self.dx - .5).astype(int)
        frac = self.x / self.dx - base
        weights = np.stack([.5 * (1.5 - frac)**2, .75 - (frac - 1)**2, .5 * (frac - .5)**2], axis=1)
        for offset in self.offsets:
            node = base + offset
            if (node < 0).any() or (node >= self.n).any():
                raise RuntimeError('Particles left the supported simulation grid; result was not published.')
            index = np.ravel_multi_index(node.T, (self.n,) * self.d)
            weight = np.prod(weights[:, offset, np.arange(self.d)], axis=1)
            yield index, weight, (np.asarray(offset) - frac) * self.dx

    def step(self, dt):
        self.grid_mass.fill(0); self.grid_v.fill(0)
        self.deformation = (np.eye(self.d) + dt * self.affine) @ self.deformation
        tau, jacobian = stress(self.deformation, self.liquid)
        self.max_volume_error = max(self.max_volume_error, float(np.max(np.abs(jacobian[self.liquid] - 1))))
        # A liquid carries volume, but not elastic shear history.
        self.deformation[self.liquid] = jacobian[self.liquid, None, None]**(1 / self.d) * np.eye(self.d)
        affine = self.masses[:, None, None] * self.affine - dt * self.volume * 4 / self.dx**2 * tau
        stencil = list(self.stencil())
        for index, weight, dpos in stencil:
            np.add.at(self.grid_mass, index, weight * self.masses)
            momentum = self.masses[:, None] * self.v + np.einsum('nij,nj->ni', affine, dpos)
            np.add.at(self.grid_v, index, weight[:, None] * momentum)
        self.max_mass_error = max(self.max_mass_error, abs(self.grid_mass.sum() - self.masses.sum()) / self.masses.sum())
        active = self.grid_mass > 1e-12
        self.grid_v[active] /= self.grid_mass[active, None]
        self.grid_v[active] += dt * self.gravity
        self.body_velocity += dt * self.gravity
        impulse, contacts = contact(self.grid_positions, self.grid_v, self.grid_mass,
                                    self.body_center, self.body_velocity, self.radius + .3 * self.dx, self.body_mass)
        self.contact_impulse += impulse; self.contact_count += contacts
        for axis in range(self.d):
            low = self.grid_positions[:, axis] < 3 * self.dx
            high = self.grid_positions[:, axis] > 1 - 3 * self.dx
            self.grid_v[low, axis] = np.maximum(self.grid_v[low, axis], 0.)
            self.grid_v[high, axis] = np.minimum(self.grid_v[high, axis], 0.)
        self.v.fill(0); self.affine.fill(0)
        for index, weight, dpos in stencil:
            velocity = self.grid_v[index]
            self.v += weight[:, None] * velocity
            self.affine += (4 / self.dx**2 * weight)[:, None, None] * velocity[:, :, None] * dpos[:, None, :]
        self.x += dt * self.v
        self.body_center += dt * self.body_velocity
        for axis in range(self.d):
            lo, hi = 3 * self.dx + self.radius, 1 - 3 * self.dx - self.radius
            if self.body_center[axis] < lo:
                self.body_center[axis] = lo; self.body_velocity[axis] = max(0., self.body_velocity[axis])
            if self.body_center[axis] > hi:
                self.body_center[axis] = hi; self.body_velocity[axis] = min(0., self.body_velocity[axis])
        if not np.isfinite(self.x).all() or not np.isfinite(self.v).all() or np.max(np.linalg.norm(self.v, axis=1)) > 50:
            raise RuntimeError('Demo numerical stability check failed; no successful result was published.')
        self.time += dt

    def snapshot(self):
        return {'time_s': round(self.time, 6), 'positions': self.x.round(5).tolist(),
                'rigid_center': self.body_center.round(6).tolist(),
                'rigid_velocity_m_s': self.body_velocity.round(6).tolist(),
                'kinetic_energy_j': float(.5 * np.sum(self.masses[:, None] * self.v**2) + .5 * self.body_mass * (self.body_velocity @ self.body_velocity))}

    def run(self, check=lambda: None, *, wall_seconds=90):
        start = time.monotonic(); frames = [self.snapshot()]; steps = 0
        for target in np.linspace(0, self.config['duration_s'], self.config['frames'])[1:]:
            while self.time < target - 1e-10:
                check()
                if time.monotonic() - start > wall_seconds:
                    raise TimeoutError('Coupled demo reached its 90-second CPU budget; reduce resolution or duration.')
                speed = max(float(np.max(np.linalg.norm(self.v, axis=1))), float(np.linalg.norm(self.body_velocity)))
                dt = min(.00025, .15 * self.dx / (20. + speed), target - self.time)
                if dt < 1e-8 or steps >= 10000:
                    raise RuntimeError('Coupled demo exceeded its bounded integration steps')
                self.step(dt); steps += 1
            frames.append(self.snapshot())
        return {'engine': 'Portable bounded NumPy APIC/MPM demo', 'compute': 'cpu',
                'config': self.config, 'units': 'metres, seconds, kilograms; 2D uses one-metre thickness',
                'particle_count': len(self.x), 'materials': np.where(self.liquid, 0, 1).tolist(),
                'material_names': ['water-like liquid', 'elastic block'], 'rigid_radius_m': self.radius,
                'tank_bounds_m': [3 * self.dx, 1 - 3 * self.dx],
                'frames': frames, 'metrics': {'steps': steps, 'elapsed_seconds': round(time.monotonic() - start, 3),
                    'maximum_relative_mass_transfer_error': self.max_mass_error,
                    'maximum_liquid_volume_change_fraction': self.max_volume_error,
                    'rigid_contact_samples': self.contact_count, 'accumulated_contact_impulse_kg_m_s': self.contact_impulse},
                'limitations': list(LIMITATIONS), 'validation': 'Numerical invariants and bounded demonstrations only; no engineering validation.'}
