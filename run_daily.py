import argparse
import os
import re

import requests

from github import Github
from github.ContentFile import ContentFile  # type: ignore
from github.Issue import Issue  # type: ignore


from config import (
    MyNumber,
    DataDir,
    GithubWorkBranch,
    MyNumberFilenameFormat,
    TimeZone,
    MyNumberHeader,
    RunningPhoto,
    RunningActivityURL,
    RunningYearHeader,
    RunningMonthHeader,
    RunningLatestHeader,
)

from utils import (
    read_file_as_dict,
    write_dict_as_file,
    github_is_me,
    fmt_to_today_utc,
    fmt_utc_to_date_str,
    fmt_utc_to_datetime_str,
    replace_readme_comments,
    longest_consecutive_dates,
    max_days_between_dates,
    sort_dict_within_list,
    fmt_markdown_table_header,
    fmt_markdown_table_template,
    list_to_dict,
    group_my_number_by_year,
    time_to_seconds,
    seconds_to_time,
    format_pace,
    split_string,
)


def new_my_number_status(
    status_func, status_unit_str: str, days_vals: dict, desc: str, html_url: str = None
) -> dict:
    status: dict = list_to_dict(MyNumberHeader)
    days = list(sorted([i for i in days_vals.keys()]))
    vals = [i for i in days_vals.values()]

    name = desc
    if html_url:
        name = f"[{name}]({html_url})"
    status["name"] = name

    num_unit = "-"
    if status_func is not None:
        num_unit = f"{status_func(vals)}{status_unit_str}"
    status["status"] = num_unit

    status["start_day"] = days[0]
    status["latest_day"] = days[-1]
    status["win_days"] = len(days)

    streak_start, streak_end = longest_consecutive_dates(days)
    longest_streak = max_days_between_dates(streak_start, streak_end) + 1
    status["streak_start"] = streak_start
    status["streak_end"] = streak_end
    status["longest_streak"] = longest_streak

    return status


def new_my_number_status_template():
    status_header = fmt_markdown_table_header(MyNumberHeader)
    status_template = fmt_markdown_table_template(MyNumberHeader)
    status_template = (
        status_template.rstrip("\n")
        + " <!-- {streak_start} to {streak_end} --> "
        + "\n"
    )

    return status_header, status_template


def new_run_data(header, year_or_month, runs, sum_meters, sum_seconds):
    run_data = list_to_dict(header)
    if "month" in run_data:
        run_data["month"] = year_or_month
    else:
        run_data["year"] = year_or_month

    run_data["runs"] = runs
    run_data["distance"] = f"{sum_meters/1000:.2f} km"
    run_data["time"] = seconds_to_time(sum_seconds)
    run_data["avg_pace"] = format_pace(sum_meters, sum_seconds)

    return run_data


def new_run_latest(header, date_local, sum_meters, sum_seconds):
    run_latest = list_to_dict(header)
    run_latest["latest_date"] = date_local
    run_latest["distance"] = f"{sum_meters/1000:.2f} km"
    run_latest["time"] = seconds_to_time(sum_seconds)
    run_latest["avg_pace"] = format_pace(sum_meters, sum_seconds)

    return run_latest


def replace_my_number(github_token: str, repo_name: str):
    gh = Github(github_token)
    repo = gh.get_repo(repo_name)
    me = gh.get_user().login

    today_utc = fmt_to_today_utc(TimeZone)
    my_num_status_list = []

    # {
    #   "2022": [my_num_status_list],
    #   "2023": [my_num_status_list],
    #   "2024": [my_num_status_list],
    # }
    my_num_status_year = dict()

    for k, v in MyNumber.items():
        labels = v.get("label")
        desc = v.get("desc")
        status_func = v.get("status_func")
        status_unit_str = v.get("status_unit_str")

        print(f"{k} processing {labels} ...")

        issues = repo.get_issues(labels=labels, state="all", creator=me)
        if issues.totalCount <= 0:
            print(f"No issue found associated with the label({labels}).")
            continue
        issue: Issue = issues[0]

        # load from file
        file_path = os.path.join(DataDir, MyNumberFilenameFormat.format(**v))
        data: dict = read_file_as_dict(file_path)

        comments = issue.get_comments(since=today_utc.subtract(days=7))
        if comments.totalCount <= 0:
            print(f"No comment found.")

        for c in comments:
            if not github_is_me(c, me):
                continue
            text = c.body.splitlines()[0]
            created_at_day = fmt_utc_to_date_str(c.created_at, TimeZone)
            data.update({created_at_day: text})

        if not any(data):
            print("data is empty.")
            continue

        write_dict_as_file(data, file_path)

        if v.get("hide_readme", False):
            print("hide_readme is True, so hide it ...")
            continue

        status = new_my_number_status(
            status_func=status_func,
            status_unit_str=status_unit_str,
            days_vals=data,
            desc=desc,
            # html_url=issue.html_url,
        )
        print(f"{status}")
        my_num_status_list.append(status)

        data_by_year = group_my_number_by_year(data=data)
        for year, data_year in data_by_year.items():
            if year not in my_num_status_year:
                my_num_status_year[year] = []

            status_year = new_my_number_status(
                status_func=status_func,
                status_unit_str=status_unit_str,
                days_vals=data_year,
                desc=desc,
            )
            print(f"{year}: {status_year}")
            my_num_status_year[year].append(status_year)

        print(f"{k} done.")

    status_header, status_template = new_my_number_status_template()

    status_str = status_header
    my_num_status_list = sort_dict_within_list(
        my_num_status_list, key1="start_day", key2="win_days"
    )
    for status in my_num_status_list:
        status_str += status_template.format(**status)
    replace_readme_comments("README.md", status_str, "my_number")

    status_str = "\n"
    my_num_status_year = sorted(
        my_num_status_year.items(), key=lambda x: x[0], reverse=True
    )
    for year, status_list in my_num_status_year:
        status_str += f"### {year}\n"
        status_str += status_header
        status_list = sort_dict_within_list(
            status_list, key1="start_day", key2="win_days"
        )
        for status in status_list:
            status_str += status_template.format(**status)
        status_str += "\n"
    replace_readme_comments("README.md", status_str, "my_number_year")


def replace_running_year():
    try:
        r = requests.get(RunningActivityURL, timeout=30)
        if not r.ok:
            print(f"retrieve running data code: {r.status_code}")
            return
    except Exception as e:
        print(f"request to {RunningActivityURL} error: {e}")
        return

    run_year_month = dict()

    total_meters = 0
    total_seconds = 0
    total_runs = 0

    # "distance": 12025.736,
    # "moving_time": "1:23:54",
    # "moving_time": "1:41:40.917000",
    # "type": "Run",
    # "start_date_local": "2024-03-06 20:51:01"
    r_json = r.json()
    for run in r_json:
        if run["type"].lower() != "run":
            continue
        moving_time = run["moving_time"].split(".")[0]

        date_local = run["start_date_local"]
        year, month = date_local.split(" ")[0].split("-")[:2]
        meters = int(run["distance"])
        seconds = time_to_seconds(moving_time)

        total_meters += meters
        total_seconds += seconds
        total_runs += 1

        if year not in run_year_month:
            run_year_month[year] = dict()

        if month not in run_year_month[year]:
            run_year_month[year][month] = {
                "meters": [],
                "seconds": [],
            }

        run_year_month[year][month]["meters"].append(meters)
        run_year_month[year][month]["seconds"].append(seconds)

    year_header = fmt_markdown_table_header(RunningYearHeader)
    year_template = fmt_markdown_table_template(RunningYearHeader)

    month_header = fmt_markdown_table_header(RunningMonthHeader)
    month_template = fmt_markdown_table_template(RunningMonthHeader)

    run_year_str = year_header
    run_month_str = ""

    total_data = new_run_data(
        RunningYearHeader, " ", total_runs, total_meters, total_seconds
    )
    run_year_str += year_template.format(**total_data)

    for year, month_dict in sorted(
        run_year_month.items(), key=lambda x: x[0], reverse=True
    ):
        year_runs = 0
        year_meters = 0
        year_seconds = 0

        run_month_str += f"### {year}\n"
        run_month_str += month_header

        for month, data in sorted(month_dict.items(), key=lambda x: x[0], reverse=True):
            month_runs = len(data["meters"])
            month_meters = sum(data["meters"])
            month_seconds = sum(data["seconds"])

            year_runs += month_runs
            year_meters += month_meters
            year_seconds += month_seconds

            month_data = new_run_data(
                RunningMonthHeader, month, month_runs, month_meters, month_seconds
            )
            run_month_str += month_template.format(**month_data)

        year_data = new_run_data(
            RunningYearHeader, year, year_runs, year_meters, year_seconds
        )
        run_year_str += year_template.format(**year_data)

    leatest_header = fmt_markdown_table_header(RunningLatestHeader)
    latest_template = fmt_markdown_table_template(RunningLatestHeader)
    latest_num = 5
    latest_run = r_json[-latest_num:]
    latest_run_str = leatest_header
    for run in latest_run[::-1]:
        latest_data = new_run_latest(
            RunningLatestHeader,
            run["start_date_local"],
            int(run["distance"]),
            time_to_seconds(moving_time),
        )
        latest_run_str += latest_template.format(**latest_data)

    replace_readme_comments("README.md", latest_run_str, "running_latest")
    replace_readme_comments("README.md", run_year_str, "running_year")
    replace_readme_comments("README.md", run_month_str, "running_month")


def replace_running(github_token: str, repo_name: str):
    gh = Github(github_token)
    repo = gh.get_repo(repo_name)

    running = RunningPhoto.get("running")
    if not running:
        print("running is None.")
        return

    rel_path = running.get("path")

    content_file_dict = dict()
    for cf in repo.get_contents(rel_path, ref=GithubWorkBranch):
        content_file_dict.update({cf.name: cf})

    filenames = [i for i in content_file_dict.keys() if re.search(r"(\d+)_weeks*", i)]
    if not filenames:
        print("filenames is None.")

    filename = sorted(filenames)[-1]
    cf: ContentFile = content_file_dict.get(filename)
    print(f"filename: {filename}, url: {cf.html_url}")

    status_str = f'<img src="{cf.html_url}" width="35%">'
    replace_readme_comments("README.md", status_str, "running_img")

    replace_running_year()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("github_token", help="github_token")
    parser.add_argument("repo_name", help="repo_name")
    options = parser.parse_args()

    if not os.path.exists(f"{DataDir}"):
        os.mkdir(f"{DataDir}")

    replace_my_number(options.github_token, options.repo_name)
    replace_running(options.github_token, options.repo_name)
