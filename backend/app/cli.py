import argparse
import getpass

from sqlalchemy.orm import Session

from app.auth.models import Role
from app.auth.schemas import Register
from app.auth.service import AuthService
from app.config import get_settings
from app.database import make_engine
from app.products.dao import ProductDAO
from app.products.schemas import ProductCreate
from app.products.service import ProductService
from app.seed import seed_demo_data


def main():
    parser = argparse.ArgumentParser(description="Администрирование учебного кредитного кабинета")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user")
    create.add_argument("--email", required=True)
    create.add_argument("--role", choices=[role.value for role in Role], required=True)
    sub.add_parser("seed-products")
    sub.add_parser("seed-data")
    args = parser.parse_args()
    settings = get_settings()
    engine = make_engine(settings.database_url)
    with Session(engine) as session, session.begin():
        if args.command == "create-user":
            password = getpass.getpass("Пароль (не менее 10 символов): ")
            user = AuthService(session).register(
                Register(email=args.email, password=password), Role(args.role)
            )
            print(f"Создан {user.role}: {user.id}")
        elif args.command == "seed-data":
            created = seed_demo_data(session)
            print("Базовые данные созданы" if created else "Базовые данные уже загружены: пропуск")
        elif not ProductDAO(session).list():
            ProductService(session).create(
                ProductCreate(
                    name="Демо: развитие бизнеса",
                    purposes=["working_capital", "equipment", "expansion", "refinancing"],
                    min_amount="100000",
                    max_amount="10000000",
                    min_term_months=6,
                    max_term_months=60,
                    annual_rate="18",
                    min_business_age_months=6,
                    min_annual_revenue="300000",
                    max_debt_burden="0.70",
                    required_documents=["registration", "financial_statements", "bank_statement"],
                )
            )
            print("Создан демонстрационный продукт")
    engine.dispose()


if __name__ == "__main__":
    main()
