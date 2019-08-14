# -*- coding: utf-8 -*-

import torch
import torch.nn.functional as F
import torch.optim as optim
import rl_main.rl_utils as rl_utils

from rl_main.conf.constants_mine import DEEP_LEARNING_MODEL, ModelName
from rl_main.models.actor_critic_mlp import ActorCriticMLP
from rl_main.models.actor_critic_cnn import ActorCriticCNN
from rl_main.models.cnn import CNN

device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

lmbda = 0.95
eps_clip = 0.1
K_epoch = 10
c1 = 0.5
c2 = 0.01


class PPOContinuousActionAgent_v0:
    def __init__(self, env, worker_id, gamma, env_render, logger, verbose):
        self.env = env

        self.worker_id = worker_id

        # discount rate
        self.gamma = gamma

        self.trajectory = []

        # learning rate
        self.learning_rate = 0.001

        self.env_render = env_render
        self.logger = logger
        self.verbose = verbose

        self.model = rl_utils.get_rl_model(self.env)

        self.optimizer = optim.Adam(self.model.parameters(), lr=self.learning_rate)

        print("----------Worker {0}: {1}:--------".format(
            self.worker_id, "PPO",
        ))

    def put_data(self, transition):
        self.trajectory.append(transition)

    def get_trajectory_data(self):
        state_lst, action_lst, reward_lst, next_state_lst, prob_action_lst, done_mask_lst = [], [], [], [], [], []

        for transition in self.trajectory:
            s, a, r, s_prime, prob_a, done = transition

            state_lst.append(s)
            action_lst.append([a])
            reward_lst.append([r])
            next_state_lst.append(s_prime)

            prob_action_lst.append([prob_a])

            done_mask = 0 if done else 1
            done_mask_lst.append([done_mask])

        state_lst = torch.stack(state_lst)
        action_lst = torch.tensor(action_lst).to(device)
        reward_lst = torch.tensor(reward_lst).to(device)
        next_state_lst = torch.tensor(next_state_lst, dtype=torch.float).to(device)
        done_mask_lst = torch.tensor(done_mask_lst, dtype=torch.float).to(device)
        prob_action_lst = torch.tensor(prob_action_lst).to(device)

        self.trajectory.clear()
        return state_lst, action_lst, reward_lst, next_state_lst, done_mask_lst, prob_action_lst

    def train_net(self):
        state_lst, action_lst, reward_lst, next_state_lst, done_mask_lst, prob_action_lst = self.get_trajectory_data()
        loss_sum = 0.0
        for i in range(K_epoch):
            v_target = reward_lst + self.gamma * self.model.v(next_state_lst) * done_mask_lst

            delta = v_target - self.model.v(state_lst)
            delta = delta.cpu().detach().numpy()

            advantage_lst = []
            advantage = 0.0
            for delta_t in delta[::-1]:
                advantage = self.gamma * lmbda * advantage + delta_t[0]
                advantage_lst.append([advantage])
            advantage_lst.reverse()
            advantage = torch.tensor(advantage_lst, dtype=torch.float).to(device)

            pi, new_prob_action_lst = self.model.continuous_act(state_lst)
            ratio = torch.exp(torch.log(new_prob_action_lst) - torch.log(prob_action_lst))  # a/b == exp(log(a)-log(b))

            surr1 = ratio * advantage
            surr2 = torch.clamp(ratio, 1 - eps_clip, 1 + eps_clip) * advantage
            entropy = new_prob_action_lst * torch.log(prob_action_lst + 1.e-10) + \
                      (1.0 - new_prob_action_lst) * torch.log(-prob_action_lst + 1.0 + 1.e-10)

            loss = -torch.min(surr1, surr2) + c1 * F.smooth_l1_loss(self.model.v(state_lst), v_target.detach()) - c2 * entropy

            self.optimizer.zero_grad()
            loss.mean().backward()
            self.optimize_step()

            loss_sum += loss.mean().item()

        gradients = self.model.get_gradients_for_current_parameters()
        return gradients, loss_sum / K_epoch

    def optimize_step(self):
        self.optimizer.step()

    def on_episode(self, episode):
        # in CartPole-v0:
        # state = [theta, angular speed]
        state = self.env.reset()
        state = torch.tensor(state, dtype=torch.float).to(device)
        done = False
        score = 0.0

        while not done:
            if self.env_render:
                self.env.render()

            action, prob = self.model.continuous_act(state)
            next_state, reward, adjusted_reward, done, info = self.env.step(action)
            # next_state = torch.FloatTensor(next_state).float().to(device)
            # adjusted_reward = torch.FloatTensor(adjusted_reward).float().to(device)
            self.put_data((state, action, adjusted_reward, next_state, prob, done))

            state = next_state
            state = torch.tensor(state, dtype=torch.float).to(device)
            score += reward

        gradients, loss = self.train_net()
        return gradients, loss, score

    def get_parameters(self):
        return self.model.get_parameters()

    def transfer_process(self, parameters, soft_transfer, soft_transfer_tau):
        self.model.transfer_process(parameters, soft_transfer, soft_transfer_tau)
