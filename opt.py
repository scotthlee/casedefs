import numpy as np
import scipy as sp
import pandas as pd
import ortools
import time
import os

from importlib import reload
from ortools.linear_solver import pywraplp
from scipy.special import expit, erf

import tools.optimization as to


# Globals
UNIX = True
USE_TODAY = False
COMBINED = True

# Importing the original data
file_dir = base_dir + 'OneDrive - CDC/Documents/projects/az covid/'
dir_files = os.listdir(file_dir)
records = pd.read_csv(file_dir + 'rf_records.csv')

# List of symptom names and case definitions
symptom_list = [
    'fever', 'chills', 'shiver', 'ma', 'congestion',
    'sorethroat', 'cough', 'sob', 'difficultbreath', 'nauseavom',
    'headache', 'abpain', 'diarrhea', 'losstastesmell', 'fatigue'
]

today_list = [
      'fevertoday', 'chillstoday', 'shivertoday', 'muscletoday', 
      'congestiontoday', 'sorethroattoday', 'coughtoday', 'sobtoday', 
      'difficultbreathtoday', 'nauseavomtoday', 'headachetoday', 
      'abpaintoday', 'diarrheatoday', 'losstastesmelltoday', 
      'fatiguetoday'
]

# Deciding what variables to include
var_list = symptom_list

if COMBINED:
    var_list = [s + '_comb' for s in var_list]
else:
    if USE_TODAY:
        var_list += today_list

var_list += ['ant']

# Making them combined
y = records.pcr.values
X = records[var_list].values

pos = np.where(y == 1)[0]
neg = np.where(y == 0)[0]

X = np.concatenate([X[pos], X[neg]], axis=0)
y = np.concatenate([y[pos], y[neg]], axis=0)

xp = X[:len(pos), :]
xn = X[len(pos):, :]

# Setting up the simple NLP
#m = 1
#n = 4
N = X.shape[0]
Ns = X.shape[1]
bnds = ((0, 1),) * Ns
bnds += ((1, Ns),)
init = np.zeros(Ns + 1)

# Setting up the optional constraints for m and n
nA = np.concatenate([np.ones(Ns),
                     np.zeros(1)])
mA = np.concatenate([np.zeros(Ns),
                     np.ones(1)])
ncon = sp.optimize.LinearConstraint(nA, lb=1, ub=n)
mcon = sp.optimize.LinearConstraint(mA, lb=1, ub=m)

# Optional constraints for sensitivity and/or specificity
se_con = sp.optimize.NonlinearConstraint(sens, 
                                         lb=0.8, 
                                         ub=1.0)
sp_con = sp.optimize.NonlinearConstraint(spec,
                                         lb=0.8,
                                         ub=1.0)

# Running the program
start = time.time()
opt = sp.optimize.minimize(
    fun=to.j_exp,
    x0=init,
    args=(xp, xn),
    bounds=bnds
)
end = time.time()
end - start

good = opt.x.round()[:-1]
good_cols = np.where(good == 1)[0]
good_s = [var_list[i] for i in good_cols]
good_s
to.j_lin(good, xp, xn, opt.x.round()[-1])

# Now trying the compound program
Nc = 3
z_bnds = ((0, 1),) * Ns * Nc
m_bnds = ((0, 16),) * Nc
bnds = z_bnds + m_bnds

# Constraint so that no symptom appears in more than one combo
z_con_mat = np.concatenate([np.identity(Ns)] * Nc, axis=1)
m_con_mat = np.zeros((Ns, Nc))
nmax_mat = np.concatenate([z_con_mat, m_con_mat], axis=1)
nmax_cons = sp.optimize.LinearConstraint(nmax_mat, lb=0, ub=1)

# Constraint so that m <= n for any combo
z_c_rows = [np.ones(Ns)] * Nc
z_c_mat = np.zeros((Nc, Ns * Nc))
for i, r in enumerate(z_c_rows):
    start = i * Ns
    end = start + Ns
    z_c_mat[i, start:end] = r

z_c_mat = np.concatenate([z_c_mat, np.identity(Nc) * -1],
                         axis=1)
mn_cons = sp.optimize.LinearConstraint(z_c_mat, 
                                       lb=0, 
                                       ub=np.inf)
mn_cons = sp.optimize.NonlinearConstraint(to.m_morethan_n, 
                                          lb=-np.inf, 
                                          ub=0.999)

# Constraint that at least one combo must have m >= 1
m_sum = np.concatenate([np.zeros(Ns * Nc),
                        np.ones(Nc)])
m_sum_cons = sp.optimize.LinearConstraint(m_sum, lb=1, ub=np.inf)

init = np.zeros(len(bnds))
#init = np.ones(len(bnds))
#init = np.random.choice([0, 1], len(bnds))

start = time.time()
opt = sp.optimize.minimize(
    fun=to.j_exp_comp,
    x0=init,
    args=(xp, xn, Nc),
    bounds=bnds,
    method='trust-constr',
    constraints=[nmax_cons, m_sum_cons, mn_cons]
)
end = time.time()
start - end

solution = opt.x.round()
mvals = solution[-Nc:]
good = solution[:-Nc].reshape((Ns, Nc), order='F')
to.j_lin_comp(good, mvals, X, y)

# And now trying it as a linear program; first setting up the constraints
H = 100
N = X.shape[0]
npos = len(pos)
nneg = len(neg)

T_con = np.identity(N) * H * -1
m_con_pos = np.ones((npos, 1))
m_con_neg = np.ones((nneg, 1)) * -1
m_con = np.concatenate([m_con_pos, m_con_neg])
Z_con = np.concatenate([xp * -1, xn], axis=0)
mn_con = np.concatenate([np.ones(Ns) * -1, 
                         np.ones(1), 
                         np.zeros(N)]).reshape(1, -1)
con_mat = np.concatenate([Z_con, m_con, T_con], axis=1)
con_mat = np.concatenate([con_mat, mn_con], axis=0).astype(np.int16)

# Setting up the bounds on the variables
bnds = [(0, 1)] * Ns
bnds += [(1, Ns)]
bnds += [(0, 1)] * N

# Setting up the bounds on the constraints
con_bounds = np.concatenate([np.zeros(npos), 
                             np.ones(nneg) * -1,
                             np.zeros(1)])

# And setting up the objective
divs = [1 / xp.shape[0]] * xp.shape[0]
divs += [1 / xn.shape[0]] * xn.shape[0]
obj = np.concatenate([np.zeros(Ns),
                      np.zeros(1),
                      np.array(divs)])

opt = sp.optimize.linprog(
    c=obj,
    A_ub=con_mat,
    b_ub=con_bounds,
    method='highs',
    bounds=bnds
)

# Trying with or tools
divs = [1 / (xp.shape[0] / 10000)] * xp.shape[0]
divs += [1 / (xn.shape[0] / 10000)] * xn.shape[0]
obj = np.concatenate([np.zeros(Ns),
                      np.zeros(1),
                      np.array(divs)])

def create_data_model():
    """Stores the data for the problem."""
    data = {}
    data['constraint_coeffs'] = [[int(i) for i in j]for j in con_mat]
    data['bounds'] = [i for i in con_bounds]
    data['obj_coeffs'] = [int(i) for i in obj]
    data['num_vars'] = con_mat.shape[1]
    data['num_constraints'] = con_mat.shape[0]
    return data

data = create_data_model()

# Create the mip solver with the SCIP backend.
solver = pywraplp.Solver.CreateSolver('SCIP')

x = {}
for j in range(data['num_vars']):
    x[j] = solver.IntVar(bnds[j][0], bnds[j][1], '')

neg_inf = -solver.infinity()
for i in range(data['num_constraints']):
    constraint = solver.RowConstraint(neg_inf, data['bounds'][i], '')
    for j in range(data['num_vars']):
        constraint.SetCoefficient(x[j], data['constraint_coeffs'][i][j])

objective = solver.Objective()
for j in range(data['num_vars']):
    objective.SetCoefficient(x[j], data['obj_coeffs'][j])

objective.SetMinimization()

status = solver.Solve()

if status == pywraplp.Solver.OPTIMAL:
    print('Objective value =', solver.Objective().Value())
    for j in range(data['num_vars']):
        print(x[j].name(), ' = ', x[j].solution_value())
    print()
    print('Problem solved in %f milliseconds' % solver.wall_time())
    print('Problem solved in %d iterations' % solver.iterations())
    print('Problem solved in %d branch-and-bound nodes' % solver.nodes())
else:
    print('The problem does not have an optimal solution.')

good = np.round([x[i].solution_value() for i in range(16)]).astype(np.int8)