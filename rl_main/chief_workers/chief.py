# -*- coding:utf-8 -*-
import pickle
import zlib

import torch

from rl_main.models.cnn import CNN
from rl_main.utils import exp_moving_average, get_environment

from rl_main.models.actor_critic_mlp import ActorCriticMLP

import matplotlib.pyplot as plt
from matplotlib import gridspec

from collections import deque
from rl_main.conf.constants_mine import *

env = get_environment()

device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")


class Chief:
    def __init__(self, logger):
        self.logger = logger
        self.messages_received_from_workers = {}

        self.NUM_DONE_WORKERS = 0
        self.scores = {}
        self.losses = {}

        self.score_over_recent_100_episodes = {}

        self.success_done_episode = {}
        self.success_done_score = {}

        self.global_max_ema_score = 0
        self.global_min_ema_loss = 1000000000

        self.episode_chief = 0
        self.num_messages = 0

        self.hidden_size = [HIDDEN_1_SIZE, HIDDEN_2_SIZE, HIDDEN_3_SIZE]

        # [DEEP_LEARNING_MODELS]
        if DEEP_LEARNING_MODEL == ModelName.ActorCriticMLP:
            self.model = ActorCriticMLP(
                s_size=env.n_states,
                a_size=env.n_actions,
                continuous=env.continuous,
                device=device
            ).to(device)
        elif DEEP_LEARNING_MODEL == ModelName.CNN:
            self.model = CNN(
                input_height=env.cnn_input_height,
                input_width=env.cnn_input_width,
                input_channels=env.cnn_input_channels,
                a_size=env.n_actions,
                continuous=env.continuous,
                device=device
            ).to(device)
        else:
            self.model = None

        for worker_id in range(NUM_WORKERS):
            self.scores[worker_id] = []
            self.losses[worker_id] = []

            self.success_done_episode[worker_id] = []
            self.success_done_score[worker_id] = []

            self.score_over_recent_100_episodes[worker_id] = deque(maxlen=WIN_AND_LEARN_FINISH_CONTINUOUS_EPISODES)

    def update_loss_score(self, msg_payload):
        worker_id = msg_payload['worker_id']
        loss = msg_payload['loss']
        score = msg_payload['score']

        self.losses[worker_id].append(loss)
        self.scores[worker_id].append(score)
        self.score_over_recent_100_episodes[worker_id].append(score)

    def save_graph(self):
        plt.clf()

        fig = plt.figure(figsize=(30, 2 * NUM_WORKERS))
        gs = gridspec.GridSpec(
            nrows=NUM_WORKERS,  # row 몇 개
            ncols=2,  # col 몇 개
            width_ratios=[5, 5],
            hspace=0.2
        )

        max_episodes = 1
        for worker_id in range(NUM_WORKERS):
            if len(self.scores[worker_id]) > max_episodes:
                max_episodes = len(self.scores[worker_id])

        ax = {}
        for row in range(NUM_WORKERS):
            ax[row] = {}
            for col in range(2):
                ax[row][col] = plt.subplot(gs[row * 2 + col])
                ax[row][col].set_xlim([0, max_episodes])
                ax[row][col].tick_params(axis='both', which='major', labelsize=10)

        for worker_id in range(NUM_WORKERS):
            ax[worker_id][0].plot(
                range(len(self.losses[worker_id])),
                self.losses[worker_id],
                c='blue'
            )
            ax[worker_id][0].plot(
                range(len(self.losses[worker_id])),
                exp_moving_average(self.losses[worker_id], EMA_WINDOW),
                c='green'
            )

            ax[worker_id][1].plot(
                range(len(self.scores[worker_id])),
                self.scores[worker_id],
                c='blue'
            )
            ax[worker_id][1].plot(
                range(len(self.scores[worker_id])),
                exp_moving_average(self.scores[worker_id], EMA_WINDOW),
                c='green'
            )

            ax[worker_id][1].scatter(
                self.success_done_episode[worker_id],
                self.success_done_score[worker_id],
                marker="*",
                s=70,
                c='red'
            )

        plt.savefig("./graphs/loss_score.png")
        plt.close('all')

    def process_message(self, topic, msg_payload):
        self.update_loss_score(msg_payload)
        self.save_graph()

        if topic == MQTT_TOPIC_EPISODE_DETAIL and MODE_GRADIENTS_UPDATE:
            self.model.accumulate_gradients(msg_payload['avg_gradients'])

        elif topic == MQTT_TOPIC_SUCCESS_DONE:
            self.success_done_episode[msg_payload['worker_id']].append(msg_payload['episode'])
            self.success_done_score[msg_payload['worker_id']].append(msg_payload['score'])

            self.NUM_DONE_WORKERS += 1
            print("BROKER CHECK! - num_of_done_workers:", self.NUM_DONE_WORKERS)

        elif topic == MQTT_TOPIC_FAIL_DONE:
            self.NUM_DONE_WORKERS += 1
            print("BROKER CHECK! - num_of_done_workers:", self.NUM_DONE_WORKERS)

        else:
            pass

    def send_transfer_ack(self, parameters_transferred):
        if MODE_PARAMETERS_TRANSFER:
            log_msg = "[SEND] TOPIC: {0}, PAYLOAD: 'episode': {1}, 'parameters_length: {2}\n".format(
                MQTT_TOPIC_TRANSFER_ACK,
                self.episode_chief,
                len(parameters_transferred)
            )

            transfer_msg = {
                "episode_chief": self.episode_chief,
                "parameters": parameters_transferred
            }
        else:
            log_msg = "[SEND] TOPIC: {0}, PAYLOAD: 'episode': {1}\n".format(
                MQTT_TOPIC_TRANSFER_ACK,
                self.episode_chief
            )

            transfer_msg = {
                "episode_chief": self.episode_chief
            }
        self.logger.info(log_msg)

        transfer_msg = pickle.dumps(transfer_msg, protocol=-1)
        transfer_msg = zlib.compress(transfer_msg)

        self.model.reset_average_gradients()

        return transfer_msg

    def send_update_ack(self):
        if MODE_GRADIENTS_UPDATE:
            log_msg = "[SEND] TOPIC: {0}, PAYLOAD: 'episode': {1}, 'global_avg_grad_length': {2}\n".format(
                MQTT_TOPIC_UPDATE_ACK,
                self.episode_chief,
                len(self.model.avg_gradients)
            )

            self.model.get_average_gradients(NUM_WORKERS - self.NUM_DONE_WORKERS)

            grad_update_msg = {
                "episode_chief": self.episode_chief,
                "avg_gradients": self.model.avg_gradients
            }
        else:
            log_msg = "[SEND] TOPIC: {0}, PAYLOAD: 'episode': {1}\n".format(
                MQTT_TOPIC_UPDATE_ACK,
                self.episode_chief
            )

            grad_update_msg = {
                "episode_chief": self.episode_chief
            }
        self.logger.info(log_msg)

        grad_update_msg = pickle.dumps(grad_update_msg, protocol=-1)
        grad_update_msg = zlib.compress(grad_update_msg)

        self.model.reset_average_gradients()

        return grad_update_msg
