import argparse
import os
import re

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
)

from utils import (
    read_file_as_dict,
    write_dict_as_file,
    github_is_me,
    fmt_to_today_utc,
    fmt_utc_to_date_str,
    replace_readme_comments,
    longest_consecutive_dates,
    max_days_between_dates,
    sort_dict_within_list,
    fmt_markdown_table_header,
    fmt_markdown_table_template,
    list_to_dict,
)


def replace_my_number(github_token: str, repo_name: str):
    gh = Github(github_token)
    repo = gh.get_repo(repo_name)
    me = gh.get_user().login

    today_utc = fmt_to_today_utc(TimeZone)
    my_num_stat_list = []

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

        comments = issue.get_comments(since=today_utc.subtract(days=7))
        if comments.totalCount <= 0:
            print(f"No comment found.")
            continue

        file_path = os.path.join(DataDir, MyNumberFilenameFormat.format(**v))
        data: dict = read_file_as_dict(file_path)

        for c in comments:
            if not github_is_me(c, me):
                continue
            text = c.body.splitlines()[0]
            created_at_day = fmt_utc_to_date_str(c.created_at, TimeZone)
            data.update({created_at_day: text})

        write_dict_as_file(data, file_path)

        if v.get("skip_readme"):
            print("skip_readme is True, so skip it ...")
            continue

        stat: dict = list_to_dict(MyNumberHeader)
        days = list(sorted([i for i in data.keys()]))
        vals = [i for i in data.values()]

        stat["name"] = f"[{desc.split('_')[-1]}]({issue.html_url})"
        status = "-"
        if status_func is not None:
            status = f"{status_func(vals)}{status_unit_str}"
        stat["status"] = status

        stat["start_day"] = days[0]
        stat["latest_day"] = days[-1]
        stat["win_days"] = len(days)

        streak_start, streak_end = longest_consecutive_dates(days)
        longest_streak = max_days_between_dates(streak_start, streak_end) + 1
        stat["streak_start"] = streak_start
        stat["streak_end"] = streak_end
        stat["longest_streak"] = longest_streak

        my_num_stat_list.append(stat)
        print(f"{stat}")
        print(f"{k} done.")

    my_num_stat_str = fmt_markdown_table_header(MyNumberHeader)
    stat_template = fmt_markdown_table_template(MyNumberHeader)
    stat_template = (
        stat_template.rstrip("\n") + " <!-- {streak_start} to {streak_end} --> " + "\n"
    )

    my_num_stat_list = sort_dict_within_list(
        my_num_stat_list, key1="start_day", key2="win_days"
    )
    for stat in my_num_stat_list:
        my_num_stat_str += stat_template.format(**stat)

    replace_readme_comments("README.md", my_num_stat_str, "my_number")


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

    stat_str = f'<img src="{cf.html_url}" width="35%">'
    replace_readme_comments("README.md", stat_str, "running")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("github_token", help="github_token")
    parser.add_argument("repo_name", help="repo_name")
    options = parser.parse_args()

    if not os.path.exists(f"{DataDir}"):
        os.mkdir(f"{DataDir}")

    replace_my_number(options.github_token, options.repo_name)
    replace_running(options.github_token, options.repo_name)
