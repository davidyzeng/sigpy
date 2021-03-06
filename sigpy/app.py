# -*- coding: utf-8 -*-
"""Applications.
"""
import numpy as np

from tqdm import tqdm
from sigpy import linop, prox, util, config
from sigpy.alg import PowerMethod, GradientMethod, \
    ConjugateGradient, PrimalDualHybridGradient

if config.cupy_enabled:
    import cupy as cp


class App(object):
    """Iterative algorithm application. Each App has its own Alg.

    Args:
        alg (Alg): Alg object.
        show_pbar (bool): toggle whether show progress bar.

    Attributes:
        alg (Alg)
        show_pbar (bool)

    """
    def __init__(self, alg, show_pbar=True):
        self.alg = alg
        self.show_pbar = show_pbar

    def _init(self):
        return

    def _pre_update(self):
        return

    def _post_update(self):
        return

    def _summarize(self):
        return

    def _cleanup(self):
        return

    def _output(self):
        return

    def run(self):
        self._init()
        self.alg.init()
        if self.show_pbar:
            self.pbar = tqdm(total=self.alg.max_iter,
                             desc=self.__class__.__name__)

        while(not self.alg.done()):
            self._pre_update()
            self.alg.update()
            self._post_update()
            self._summarize()
            if self.show_pbar:
                self.pbar.update()

        self.alg.cleanup()
        self._cleanup()
        if self.show_pbar:
            self.pbar.close()

        return self._output()


class MaxEig(App):
    """Computes maximum eigenvalue of a Linop.

    Args:
        A (Linop): Hermitian linear operator.
        dtype (Dtype): Data type.
        device (Device): Device.

    Attributes:
        x (int): Eigenvector with largest eigenvalue.

    Output:
        max_eig (int): Largest eigenvalue of A.

    """
    def __init__(self, A, dtype=np.complex, device=util.cpu_device,
                 max_iter=30, show_pbar=True):
        self.x = util.empty(A.ishape, dtype=dtype, device=device)
        alg = PowerMethod(A, self.x, max_iter=max_iter)
        super().__init__(alg, show_pbar=show_pbar)

    def _init(self):
        util.move_to(self.x, util.randn_like(self.x))

    def _summarize(self):
        if self.show_pbar:
            self.pbar.set_postfix(max_eig='{0:.2E}'.format(self.alg.max_eig))

    def _output(self):
        return self.alg.max_eig
    

class LinearLeastSquares(App):
    r"""Linear least squares application.

    Solves for the following problem, with optional weights and regularizations:

    .. math::
        \min_x \frac{1}{2} \| A x - y \|_W^2 + g(G x) + 
        \frac{\lambda}{2} \| R x \|_2^2 + \frac{\mu}{2} \| x - z \|_2^2

    Three algorithms can be used: `ConjugateGradient`, `GradientMethod`,
    and `PrimalDualHybridGradient`. If `alg_name` is None, `ConjugateGradient` is used
    when `proxg` is not specified. If `proxg` is specified,
    then `GradientMethod` is used when `G` is specified, and `PrimalDualHybridGradient` is
    used otherwise.

    Args:
        A (Linop): Forward linear operator.
        y (array): Observation.
        x (array): Solution.
        proxg (Prox): Proximal operator of g.
        lamda (float): l2 regularization parameter.
        g (None or function): Regularization function. 
            Only used for when `save_objective_values` is true.
        G (None or Linop): Regularization linear operator.
        R (None or Linop): l2 regularization linear operator.
        weights (float or array): Weights for least squares.
        mu (float): l2 bias regularization parameter.
        z (float or array): Bias for l2 regularization.
        alg_name (str): {`'ConjugateGradient'`, `'GradientMethod'`, `'PrimalDualHybridGradient'`}.
        max_iter (int): Maximum number of iterations.
        P (Linop): Preconditioner for ConjugateGradient.

        .. math::
            \min_u \frac{1}{2} \|u - v\|_2^2 + \frac{\alpha}{2} \|D^{-1 / 2}(u - y)\|_2^2

        alpha (None or float): Step size for `GradientMethod`.
        accelerate (bool): Toggle Nesterov acceleration for `GradientMethod`.
        max_power_iter (int): Maximum number of iterations for power method. 
            Used for `GradientMethod` when `alpha` is not specified,
            and for `PrimalDualHybridGradient` when `tau` or `sigma` is not specified.
        tau (float): Primal step-size for `PrimalDualHybridGradient`.
        sigma (float): Dual step-size for `PrimalDualHybridGradient`.
        save_objective_values (bool): Toggle saving objective value.

    """
    def __init__(self, A, y, x, proxg=None,
                 lamda=0, G=None, g=None, R=None, weights=None, mu=0, z=0,
                 alg_name=None, max_iter=100,
                 P=None, alpha=None, max_power_iter=10, accelerate=True,
                 tau=None, sigma=None,
                 save_objective_values=False, show_pbar=True):
        self.A = A
        self.y = y
        self.x = x
        self.proxg = proxg
        self.lamda = lamda
        self.G = G
        self.g = g
        self.R = R
        self.weights = weights
        self.mu = mu
        self.z = z
        self.alg_name = alg_name
        self.max_iter = max_iter
        self.P = P
        self.alpha = alpha
        self.max_power_iter = max_power_iter
        self.accelerate = accelerate
        self.tau = tau
        self.sigma = sigma
        self.save_objective_values = save_objective_values
        self.show_pbar = show_pbar
        
        self._get_alg()

    def _init(self):
        if isinstance(self.alg, ConjugateGradient):
            if self.weights is not None:
                with util.get_device(self.y):
                    y = self.weights * self.y
            else:
                y = self.y

            with util.get_device(self.x):
                self.alg.b = self.A.H(y)
                if self.mu != 0:
                    util.axpy(self.alg.b, self.mu, self.z)

        elif isinstance(self.alg, GradientMethod):
            if self.alpha is None:
                self._get_alpha()
        elif isinstance(self.alg, PrimalDualHybridGradient):
            if self.tau is None and self.sigma is not None:
                self._get_tau()
            if self.tau is not None and self.sigma is None:
                self._get_sigma()
            elif self.tau is None and self.sigma is None:
                self.alg.sigma = 1
                self._get_tau()
                
        if self.save_objective_values:
            self.objective_values = []

    def _summarize(self):
        if self.save_objective_values:
            self.objective_values.append(self.objective())

        if self.show_pbar:
            if self.save_objective_values:
                self.pbar.set_postfix(obj='{0:.2E}'.format(self.objective_values[-1]))
            else:
                self.pbar.set_postfix(resid='{0:.2E}'.format(self.alg.resid))

    def _output(self):
        return self.x

    def _cleanup(self):
        if isinstance(self.alg, ConjugateGradient):
            del self.alg.b
            
    def _get_alg(self):
        if self.alg_name is None:
            if self.proxg is None:
                self.alg_name = 'ConjugateGradient'
            elif self.G is None:
                self.alg_name = 'GradientMethod'
            else:
                self.alg_name = 'PrimalDualHybridGradient'

        if self.alg_name == 'ConjugateGradient':
            if self.proxg is not None:
                raise ValueError('ConjugateGradient cannot have proxg specified.')

            self._get_ConjugateGradient()
        elif self.alg_name == 'GradientMethod':
            if self.G is not None:
                raise ValueError('GradientMethod cannot have G specified.')

            self._get_GradientMethod()
        elif self.alg_name == 'PrimalDualHybridGradient':
            if self.R is not None:
                raise ValueError('PrimalDualHybridGradient cannot have R specified.'
                                 'Please consider stacking R with A.')

            self._get_PrimalDualHybridGradient()
        else:
            raise ValueError('Invalid alg_name: {alg_name}.'.format(alg_name=self.alg_name))

    def _get_ConjugateGradient(self):
        I = linop.Identity(self.x.shape)
        if self.weights is not None:
            W = linop.Multiply(self.A.oshape, self.weights)
            AHA = self.A.H * W * self.A
        else:
            AHA = self.A.H * self.A
            
        if self.lamda != 0:
            if self.R is None:
                AHA += self.lamda * I
            else:
                AHA += self.lamda * self.R.H * self.R

        if self.mu != 0:
            AHA += self.mu * I

        self.alg = ConjugateGradient(AHA, None, self.x, P=self.P,
                                     max_iter=self.max_iter)

    def _get_GradientMethod(self):
        def gradf(x):
            with util.get_device(self.y):
                r = self.A(x)
                r -= self.y
                if self.weights is not None:
                    r *= self.weights
                
            with util.get_device(self.x):
                gradf_x = self.A.H(r)

                if self.lamda != 0:
                    if self.R is None:
                        util.axpy(gradf_x, self.lamda, x)
                    else:
                        util.axpy(gradf_x, self.lamda, self.R.H(self.R(x)))

                if self.mu != 0:
                    util.axpy(gradf_x, self.mu, x - self.z)

                return gradf_x

        self.alg = GradientMethod(gradf, self.x, self.alpha, proxg=self.proxg,
                                  max_iter=self.max_iter, accelerate=self.accelerate)

    def _get_PrimalDualHybridGradient(self):
        with util.get_device(self.y):
            if self.weights is not None:
                weights_sqrt = self.weights**0.5
                y = -weights_sqrt * self.y
                W_sqrt = linop.Multiply(self.A.oshape, weights_sqrt)
                A = W_sqrt * self.A
            else:
                y = -self.y
                A = self.A

        if self.proxg is None:
            proxg = prox.NoOp(self.x.shape)
        else:
            proxg = self.proxg

        if self.lamda > 0 or self.mu > 0:
            def gradh(x):
                with util.get_device(self.x):
                    gradh_x = 0
                    if self.lamda > 0:
                        if self.R is None:
                            gradh_x += self.lamda * x
                        else:
                            gradh_x += self.lamda * self.R.H(self.R(x))

                    if self.mu > 0:
                        gradh_x += self.mu * (x - self.z)

                    return gradh_x
            
            if self.R is None:
                gamma_primal = self.lamda + self.mu
            else:
                gamma_primal = self.mu

        else:
            gradh = None
            gamma_primal = 0

        if self.G is None:
            proxfc = prox.L2Reg(y.shape, 1, y=y)
            u = util.zeros_like(y)
                
            self.alg = PrimalDualHybridGradient(proxfc, proxg, A, A.H, self.x, u,
                                                self.tau, self.sigma, gradh=gradh,
                                                gamma_primal=gamma_primal, gamma_dual=1,
                                                max_iter=self.max_iter)
        else:
            A = linop.Vstack([A, self.G])
            proxf1c = prox.L2Reg(self.y.shape, 1, y=y)
            proxf2c = prox.Conj(self.proxg)
            proxfc = prox.Stack([proxf1c, proxf2c])
            proxg = prox.NoOp(self.x.shape)

            u = util.zeros(A.oshape, dtype=self.y.dtype, device=util.get_device(self.y))
            self.alg = PrimalDualHybridGradient(proxfc, proxg, A, A.H, self.x, u,
                                                self.tau, self.sigma,
                                                gamma_primal=gamma_primal,
                                                gradh=gradh, max_iter=self.max_iter)

    def _get_alpha(self):
        I = linop.Identity(self.x.shape)
        if self.weights is not None:
            W = linop.Multiply(self.A.oshape, self.weights)
            AHA = self.A.H * W * self.A
        else:
            AHA = self.A.H * self.A

        if self.lamda != 0:
            if self.R is None:
                AHA += self.lamda * I
            else:
                AHA += self.lamda * self.R.H * self.R

        if self.mu != 0:
            AHA += self.mu * I

        device = util.get_device(self.x)
        max_eig_app = MaxEig(AHA, dtype=self.x.dtype,
                             device=device, max_iter=self.max_power_iter,
                             show_pbar=self.show_pbar)

        with device:
            self.alg.alpha = 1 / max_eig_app.run()

    def _get_tau(self):
        if self.weights is not None:
            with util.get_device(self.y):
                weights_sqrt = self.weights**0.5

            W_half = linop.Multiply(self.A.oshape, weights_sqrt)
            A = W_half * self.A
        else:
            A = self.A
            
        if self.G is not None:
            A = linop.Vstack([A, self.G])
            
        S = linop.Multiply(A.oshape, self.alg.sigma)
        AHA = A.H * S * A

        device = util.get_device(self.x)
        max_eig_app = MaxEig(AHA, dtype=self.x.dtype,
                             device=device, max_iter=self.max_power_iter,
                             show_pbar=self.show_pbar)

        with device:
            self.alg.tau = 1 / (max_eig_app.run() + self.lamda + self.mu)

    def _get_sigma(self):
        if self.weights is not None:
            with util.get_device(self.y):
                weights_sqrt = self.weights**0.5

            W_half = linop.Multiply(self.A.oshape, weights_sqrt)
            A = W_half * self.A
        else:
            A = self.A
            
        if self.G is not None:
            A = linop.Vstack([A, self.G])
            
        T = linop.Multiply(A.ishape, self.alg.tau)
        AAH = A * T * A.H

        device = util.get_device(self.x)
        max_eig_app = MaxEig(AAH, dtype=self.x.dtype,
                             device=device, max_iter=self.max_power_iter,
                             show_pbar=self.show_pbar)

        with device:
            self.alg.sigma = 1 / max_eig_app.run()

    def objective(self):
        device = util.get_device(self.y)
        xp = device.xp
        with device:
            r = self.A(self.x) - self.y
            if self.weights is not None:
                r *= self.weights**0.5

            obj = 1 / 2 * util.norm2(r)
            if self.lamda > 0:
                if self.R is None:
                    obj += self.lamda / 2 * util.norm2(self.x)
                else:
                    obj += self.lamda / 2 * util.norm2(self.R(self.x))

            if self.mu != 0:
                obj += self.mu / 2 * util.norm2(self.x - self.z)

            if self.proxg is not None:
                if self.g is None:
                    raise ValueError('Cannot compute objective when proxg is specified,'
                                     'but g is not.')
                
                if self.G is None:
                    obj += self.g(self.x)
                else:
                    obj += self.g(self.G(self.x))

            obj = util.asscalar(obj)
            return obj


class L2ConstrainedMinimization(App):
    """L2 contrained minimization application.

    Solves for problem:
    min g(G x)
    s.t. ||A x - y||_2 <= eps

    Args:
        A (Linop): Forward model linear operator.
        y (array): Observation.
        proxg (Prox): Proximal operator of objective.
        eps (float): Residual.

    """
    def __init__(self, A, y, x, proxg, eps, G=None, weights=None,
                 max_iter=100, tau=None, sigma=None, theta=1,
                 show_pbar=True):

        self.x = x

        if weights is not None:
            with util.get_device(y):
                weights_sqrt = weights**0.5
                y = weights_sqrt * y

            W_sqrt = linop.Multiply(A.oshape, weights_sqrt)
            A = W_sqrt * A

        if G is None:
            self.max_eig_app = MaxEig(A.H * A, dtype=x.dtype, device=util.get_device(x))

            proxfc = prox.Conj(prox.L2Proj(A.oshape, eps, y=y))
            self.u = util.zeros_like(y)
            alg = PrimalDualHybridGradient(proxfc, proxg, A, A.H, self.x, self.u,
                                           tau, sigma, max_iter=max_iter)
        else:
            AG = linop.Vstack([A, G])
            self.max_eig_app = MaxEig(AG.H * AG,
                                      dtype=x.dtype, device=util.get_device(x))

            proxf1 = prox.L2Proj(A.oshape, eps, y=y)
            proxf2 = proxg
            proxfc = prox.Conj(prox.Stack([proxf1, proxf2]))
            proxg = prox.NoOp(A.ishape)

            self.u = util.zeros(AG.oshape, dtype=x.dtype, device=util.get_device(x))
            alg = PrimalDualHybridGradient(proxfc, proxg, AG, AG.H, self.x, self.u,
                                           tau, sigma, max_iter=max_iter)

        super().__init__(alg, show_pbar=show_pbar)

    def _init(self):
        if self.alg.tau is None or self.alg.sigma is None:
            self.alg.tau = 1
            self.alg.sigma = 1 / self.max_eig_app.run()

    def _summarize(self):
        if self.show_pbar:
            self.pbar.set_postfix(resid='{0:.2E}'.format(self.alg.resid))

    def _output(self):
        return self.x
